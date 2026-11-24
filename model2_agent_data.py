from __future__ import annotations

import json
import sqlite3
import subprocess
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from model2_config import (
    MODEL_2_ACCOUNT_ID,
    MODEL_2_VERSION,
    get_model2_paths,
)
from model2_candidate_ranking import scan_model2_candidates


NEW_YORK = ZoneInfo("America/New_York")
ZERO = Decimal("0")

TASKS = {
    "collector": "Paper Trading - Intraday Collection",
    "decision": "Paper Trading - Model 2 Daily Decision",
    "execution": "Paper Trading - Model 2 Guarded Execution",
    "expiry": "Paper Trading - Model 2 Stale Order Cleanup",
}


@dataclass
class Lot:
    quantity: int
    price: Decimal


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value))


def _paths() -> tuple[Path, Path]:
    paths = get_model2_paths()
    return (
        Path(paths.model2_database).expanduser().resolve(),
        Path(paths.observation_database).expanduser().resolve(),
    )


def _ro_connection(database: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(
        database.as_uri() + "?mode=ro",
        uri=True,
        timeout=10,
    )
    connection.execute("PRAGMA query_only = ON")
    return connection


def load_portfolio() -> dict[str, Any]:
    model2_db, observation_db = _paths()

    with _ro_connection(model2_db) as connection:
        account = connection.execute(
            """
            SELECT starting_cash
            FROM paper_accounts
            WHERE account_id = ?
            """,
            (MODEL_2_ACCOUNT_ID,),
        ).fetchone()

        if account is None:
            raise RuntimeError("Model 2 account not found.")

        starting_cash = _decimal(account[0])

        fills = connection.execute(
            """
            SELECT
                fill_id,
                order_id,
                ticker,
                side,
                quantity,
                fill_price,
                fees,
                created_at_utc
            FROM paper_fills
            ORDER BY created_at_utc, fill_id
            """
        ).fetchall()

    cash = starting_cash
    realized_pnl = ZERO
    lots: dict[str, deque[Lot]] = defaultdict(deque)

    for (
        _fill_id,
        _order_id,
        ticker,
        side,
        quantity,
        fill_price,
        fees,
        _created_at,
    ) in fills:
        ticker = str(ticker).upper()
        side = str(side).upper()
        quantity = int(quantity)
        price = _decimal(fill_price)
        fees_value = _decimal(fees or 0)

        if side == "BUY":
            cash -= Decimal(quantity) * price + fees_value
            lots[ticker].append(Lot(quantity=quantity, price=price))

        elif side == "SELL":
            cash += Decimal(quantity) * price - fees_value
            remaining = quantity

            while remaining > 0:
                if not lots[ticker]:
                    raise RuntimeError(
                        f"SELL exceeds reconstructed position: {ticker}"
                    )

                lot = lots[ticker][0]
                used = min(remaining, lot.quantity)

                realized_pnl += Decimal(used) * (price - lot.price)

                lot.quantity -= used
                remaining -= used

                if lot.quantity == 0:
                    lots[ticker].popleft()

        else:
            raise RuntimeError(f"Unsupported fill side: {side}")

    positions: list[dict[str, Any]] = []
    market_value = ZERO
    unrealized_pnl = ZERO

    with _ro_connection(observation_db) as connection:
        for ticker in sorted(lots):
            ticker_lots = [lot for lot in lots[ticker] if lot.quantity > 0]
            if not ticker_lots:
                continue

            quantity = sum(lot.quantity for lot in ticker_lots)
            cost_basis = sum(
                Decimal(lot.quantity) * lot.price
                for lot in ticker_lots
            )
            average_cost = cost_basis / Decimal(quantity)

            price_row = connection.execute(
                """
                SELECT
                    close_price,
                    bar_start_utc,
                    retrieved_at_utc
                FROM intraday_observations
                WHERE ticker = ?
                ORDER BY
                    bar_start_utc DESC,
                    retrieved_at_utc DESC
                LIMIT 1
                """,
                (ticker,),
            ).fetchone()

            price_source = "Intraday"

            if price_row is None:
                daily = connection.execute(
                    """
                    SELECT
                        close,
                        session_date
                    FROM market_bars
                    WHERE ticker = ?
                    ORDER BY session_date DESC, id DESC
                    LIMIT 1
                    """,
                    (ticker,),
                ).fetchone()

                if daily is None:
                    raise RuntimeError(f"No market price available for {ticker}.")

                current_price = _decimal(daily[0])
                price_time = str(daily[1])
                retrieved_at = None
                price_source = "Daily"
            else:
                current_price = _decimal(price_row[0])
                price_time = str(price_row[1])
                retrieved_at = str(price_row[2])

            position_value = Decimal(quantity) * current_price
            pnl = position_value - cost_basis
            return_pct = (
                pnl / cost_basis * Decimal("100")
                if cost_basis
                else ZERO
            )

            market_value += position_value
            unrealized_pnl += pnl

            positions.append(
                {
                    "ticker": ticker,
                    "shares": quantity,
                    "average_cost": average_cost,
                    "current_price": current_price,
                    "market_value": position_value,
                    "pnl": pnl,
                    "return_pct": return_pct,
                    "price_source": price_source,
                    "price_time": price_time,
                    "retrieved_at": retrieved_at,
                }
            )

    total_equity = cash + market_value
    total_pnl = total_equity - starting_cash
    total_return = (
        total_pnl / starting_cash * Decimal("100")
        if starting_cash
        else ZERO
    )
    exposure = (
        market_value / total_equity * Decimal("100")
        if total_equity
        else ZERO
    )

    return {
        "starting_cash": starting_cash,
        "cash": cash,
        "market_value": market_value,
        "total_equity": total_equity,
        "realized_pnl": realized_pnl,
        "unrealized_pnl": unrealized_pnl,
        "total_pnl": total_pnl,
        "total_return": total_return,
        "exposure": exposure,
        "positions": positions,
    }


def load_orders(
    *,
    ticker: str | None = None,
    session: str | None = None,
    status: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    model2_db, _ = _paths()

    clauses = ["model_version = ?"]
    params: list[Any] = [MODEL_2_VERSION]

    if ticker:
        clauses.append("ticker = ?")
        params.append(ticker.upper())

    if session:
        clauses.append("execution_session = ?")
        params.append(session)

    if status:
        clauses.append("status = ?")
        params.append(status.upper())

    params.append(limit)

    query = f"""
        SELECT
            order_id,
            ticker,
            side,
            quantity,
            execution_session,
            status,
            created_at_utc
        FROM paper_orders
        WHERE {" AND ".join(clauses)}
        ORDER BY execution_session DESC, order_id DESC
        LIMIT ?
    """

    with _ro_connection(model2_db) as connection:
        rows = connection.execute(query, params).fetchall()

    return [
        {
            "order_id": row[0],
            "ticker": row[1],
            "side": row[2],
            "quantity": row[3],
            "session": row[4],
            "status": row[5],
            "created_at": row[6],
        }
        for row in rows
    ]


def load_fills(
    *,
    ticker: str | None = None,
    session: str | None = None,
    limit: int = 25,
) -> list[dict[str, Any]]:
    model2_db, _ = _paths()

    clauses = ["1 = 1"]
    params: list[Any] = []

    if ticker:
        clauses.append("ticker = ?")
        params.append(ticker.upper())

    if session:
        clauses.append("execution_session = ?")
        params.append(session)

    params.append(limit)

    query = f"""
        SELECT
            fill_id,
            order_id,
            ticker,
            side,
            quantity,
            reference_price,
            fill_price,
            execution_session,
            created_at_utc
        FROM paper_fills
        WHERE {" AND ".join(clauses)}
        ORDER BY created_at_utc DESC
        LIMIT ?
    """

    with _ro_connection(model2_db) as connection:
        rows = connection.execute(query, params).fetchall()

    return [
        {
            "fill_id": row[0],
            "order_id": row[1],
            "ticker": row[2],
            "side": row[3],
            "quantity": row[4],
            "reference_price": _decimal(row[5]),
            "fill_price": _decimal(row[6]),
            "session": row[7],
            "filled_at": row[8],
        }
        for row in rows
    ]


def load_rejections(
    *,
    ticker: str | None = None,
    session: str | None = None,
    limit: int = 25,
) -> list[dict[str, Any]]:
    model2_db, _ = _paths()

    clauses = ["p.model_version = ?"]
    params: list[Any] = [MODEL_2_VERSION]

    if ticker:
        clauses.append("p.ticker = ?")
        params.append(ticker.upper())

    if session:
        clauses.append("p.execution_session = ?")
        params.append(session)

    params.append(limit)

    query = f"""
        SELECT
            p.ticker,
            p.side,
            p.quantity,
            p.execution_session,
            r.order_id,
            r.rejection_code,
            r.rejection_reason,
            r.rejected_at_utc
        FROM order_rejections AS r
        JOIN paper_orders AS p
          ON p.order_id = r.order_id
        WHERE {" AND ".join(clauses)}
        ORDER BY r.rejected_at_utc DESC
        LIMIT ?
    """

    with _ro_connection(model2_db) as connection:
        rows = connection.execute(query, params).fetchall()

    return [
        {
            "ticker": row[0],
            "side": row[1],
            "quantity": row[2],
            "session": row[3],
            "order_id": row[4],
            "code": row[5],
            "reason": row[6],
            "rejected_at": row[7],
        }
        for row in rows
    ]


def collector_health() -> dict[str, Any]:
    _, observation_db = _paths()
    now_et = datetime.now(timezone.utc).astimezone(NEW_YORK)

    with _ro_connection(observation_db) as connection:
        latest = connection.execute(
            """
            SELECT retrieved_at_utc
            FROM intraday_observations
            ORDER BY retrieved_at_utc DESC
            LIMIT 1
            """
        ).fetchone()

        today_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM intraday_observations
            WHERE substr(retrieved_at_utc, 1, 10) = ?
            """,
            (now_et.date().isoformat(),),
        ).fetchone()[0]

        ticker_count = connection.execute(
            """
            SELECT COUNT(DISTINCT ticker)
            FROM intraday_observations
            WHERE substr(retrieved_at_utc, 1, 10) = ?
            """,
            (now_et.date().isoformat(),),
        ).fetchone()[0]

    if latest is None:
        return {
            "healthy": False,
            "latest_retrieval": None,
            "age_seconds": None,
            "today_count": today_count,
            "ticker_count": ticker_count,
            "message": "No intraday observations exist.",
        }

    latest_utc = datetime.fromisoformat(str(latest[0]))
    if latest_utc.tzinfo is None:
        latest_utc = latest_utc.replace(tzinfo=timezone.utc)

    latest_et = latest_utc.astimezone(NEW_YORK)
    age_seconds = int((now_et - latest_et).total_seconds())

    healthy = age_seconds <= 20 * 60

    return {
        "healthy": healthy,
        "latest_retrieval": latest_et,
        "age_seconds": age_seconds,
        "today_count": today_count,
        "ticker_count": ticker_count,
        "message": (
            "Collector is current."
            if healthy
            else "Collector data is stale."
        ),
    }


def task_status(task_name: str) -> dict[str, Any] | None:
    script = f"""
    $x = Get-ScheduledTaskInfo -TaskName '{task_name}'
    $task = Get-ScheduledTask -TaskName '{task_name}'
    [PSCustomObject]@{{
        State = $task.State.ToString()
        LastRunTime = $x.LastRunTime
        LastTaskResult = $x.LastTaskResult
        NextRunTime = $x.NextRunTime
        NumberOfMissedRuns = $x.NumberOfMissedRuns
    }} | ConvertTo-Json -Compress
    """

    try:
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-Command",
                script,
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode != 0 or not result.stdout.strip():
            return None

        return json.loads(result.stdout.strip())

    except Exception:
        return None


def all_task_statuses() -> dict[str, dict[str, Any] | None]:
    return {
        key: task_status(name)
        for key, name in TASKS.items()
    }


def candidate_ranking(top_n: int = 10) -> dict[str, Any]:
    result = scan_model2_candidates(top_n=top_n)

    candidates = [
        {
            "rank": item.rank,
            "ticker": item.ticker,
            "momentum": item.momentum * Decimal("100"),
            "close": item.close,
            "group": item.group,
        }
        for item in result.candidates
    ]

    exits = [
        {
            "ticker": item.ticker,
            "momentum": item.momentum * Decimal("100"),
            "group": item.group,
            "reason": item.reason,
        }
        for item in result.exits
    ]

    return {
        "candidates": candidates,
        "exits": exits,
        "failures": result.failures,
        "scanned": result.scanned,
    }


def order_explanation(ticker: str) -> dict[str, Any]:
    ticker = ticker.upper()

    orders = load_orders(ticker=ticker, limit=10)
    fills = load_fills(ticker=ticker, limit=10)
    rejections = load_rejections(ticker=ticker, limit=10)

    return {
        "ticker": ticker,
        "orders": orders,
        "fills": fills,
        "rejections": rejections,
    }


def session_summary(session: str) -> dict[str, Any]:
    return {
        "session": session,
        "orders": load_orders(session=session, limit=100),
        "fills": load_fills(session=session, limit=100),
        "rejections": load_rejections(session=session, limit=100),
    }


def system_snapshot() -> dict[str, Any]:
    portfolio = load_portfolio()
    pending = load_orders(status="PENDING", limit=100)
    collector = collector_health()
    tasks = all_task_statuses()

    return {
        "portfolio": portfolio,
        "pending_orders": pending,
        "collector": collector,
        "tasks": tasks,
        "now_et": datetime.now(timezone.utc).astimezone(NEW_YORK),
    }
