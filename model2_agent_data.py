from __future__ import annotations

import json
import sqlite3
import subprocess
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import date, datetime, timezone, timedelta
from contextlib import closing
import exchange_calendars as xcals
import pandas as pd
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

MODEL_2_UNIVERSE = (
    "AAPL", "MSFT", "NVDA", "AVGO", "GOOGL", "META", "AMZN", "TSLA",
    "PLTR", "ORCL", "AMD", "MU", "TSM", "QCOM", "ASML", "LRCX", "AMAT",
    "KLAC", "LITE", "VRT", "ETN", "EQIX", "DLR", "CEG", "VST", "GEV",
    "JPM", "BAC", "C", "WFC", "GS", "MS", "JNJ", "LLY", "UNH", "ABBV",
    "XOM", "CVX", "COP", "CAT", "GE", "HON", "WMT", "COST", "HD", "NFLX",
    "LIN", "NUE", "PG", "NEE",
)

TASKS = {
    "collector": "Paper Trading - Intraday Collection",
    "decision": "Paper Trading - Model 2 Daily Decision",
    "execution": "Paper Trading - Model 2 Guarded Execution",
    "expiry": "Paper Trading - Model 2 Stale Order Cleanup",
    "equity_intraday": "Paper Trading - Model 2 Equity Snapshot",
    "equity_daily": "Paper Trading - Model 2 Daily Equity",
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


def market_movers(limit: int = 5) -> dict[str, Any]:
    model_db, obs_db = _paths()
    now = datetime.now(timezone.utc)
    cal = xcals.get_calendar("XNYS")
    today = pd.Timestamp(now.astimezone(NEW_YORK).date())
    session = cal.date_to_session(today, direction="previous")
    if session == today and now < cal.session_open(session):
        session = cal.previous_session(session)
    prior = cal.previous_session(session)
    session_date, previous_date = str(session.date()), str(prior.date())
    opened, closed = cal.session_open(session), cal.session_close(session)
    active = opened <= now < closed
    result = dict(gainers=[], losers=[], positive=0, negative=0, flat=0,
                  covered=0, universe_count=len(MODEL_2_UNIVERSE),
                  session=session_date, previous_session=previous_date, message="")
    rows = []
    with closing(_ro_connection(model_db)) as daily, closing(_ro_connection(obs_db)) as obs:
        for ticker in MODEL_2_UNIVERSE:
            def close_for(day, cutoff):
                return daily.execute("""SELECT m.close, i.retrieved_at_utc
                    FROM market_bars m JOIN ingestion_runs i ON m.run_id=i.run_id
                    WHERE m.ticker=? AND m.session_date=? AND i.safe_to_use=1
                    AND julianday(i.retrieved_at_utc)>=julianday(?)
                    AND julianday(i.retrieved_at_utc)<=julianday(?)
                    ORDER BY julianday(i.retrieved_at_utc) DESC,m.id DESC LIMIT 1""",
                    (ticker, day, cutoff.isoformat(), now.isoformat())).fetchone()
            prev = close_for(previous_date, cal.session_close(prior))
            if not prev: continue
            if active:
                mark = obs.execute("""SELECT close_price,bar_start_utc,retrieved_at_utc
                    FROM intraday_observations WHERE ticker=?
                    AND julianday(bar_start_utc)>=julianday(?)
                    AND julianday(bar_start_utc)<=julianday(?)
                    AND julianday(bar_start_utc)>=julianday(?)
                    AND julianday(retrieved_at_utc)<=julianday(?)
                    AND julianday(retrieved_at_utc)>=julianday(bar_start_utc)+1.0/1440
                    ORDER BY julianday(bar_start_utc) DESC,julianday(retrieved_at_utc) DESC,id DESC LIMIT 1""",
                    (ticker, opened.isoformat(), (now-timedelta(minutes=1)).isoformat(),
                     (now-timedelta(minutes=20)).isoformat(),now.isoformat())).fetchone()
            else:
                final = close_for(session_date, closed)
                mark = (final[0], closed.isoformat(), final[1]) if final else None
            if not mark: continue
            try:
                price, base = _decimal(mark[0]), _decimal(prev[0])
                if not price.is_finite() or not base.is_finite() or min(price,base)<=0: continue
            except (ValueError, ArithmeticError): continue
            change = price-base
            rows.append(dict(ticker=ticker,price=price,previous_close=base,change=change,
                change_pct=change/base*100,previous_session=previous_date,
                bar_time=mark[1],retrieved_at=mark[2]))
    rows.sort(key=lambda r:(-r['change_pct'],r['ticker']))
    result.update(gainers=[r for r in rows if r['change_pct']>0][:limit],
        losers=sorted((r for r in rows if r['change_pct']<0),key=lambda r:r['change_pct'])[:limit],
        positive=sum(r['change_pct']>0 for r in rows),negative=sum(r['change_pct']<0 for r in rows),
        flat=sum(r['change_pct']==0 for r in rows),covered=len(rows))
    result['message'] = (f"{session_date} vs {previous_date}: {len(rows)}/{len(MODEL_2_UNIVERSE)} covered. "
        + ("Missing or stale prices excluded." if len(rows)<len(MODEL_2_UNIVERSE) else "Exact prior session verified."))
    return result


def portfolio_allocation() -> list[dict[str, Any]]:
    portfolio = load_portfolio()
    total = portfolio["total_equity"]

    rows = []
    for position in portfolio["positions"]:
        weight = (
            position["market_value"] / total * Decimal("100")
            if total
            else ZERO
        )
        rows.append(
            {
                "name": position["ticker"],
                "value": position["market_value"],
                "weight_pct": weight,
                "kind": "position",
            }
        )

    cash_weight = (
        portfolio["cash"] / total * Decimal("100")
        if total
        else ZERO
    )
    rows.append(
        {
            "name": "CASH",
            "value": portfolio["cash"],
            "weight_pct": cash_weight,
            "kind": "cash",
        }
    )

    rows.sort(key=lambda row: row["value"], reverse=True)
    return rows


def performance_history(period: str = "ALL") -> dict[str, Any]:
    period = period.upper()
    if period not in {"1D", "1W", "1M", "3M", "YTD", "ALL"}:
        raise ValueError("Unknown chart period")
    model_db, _ = _paths()
    db = model_db.parent / "model2_performance.db"
    now = datetime.now(timezone.utc)
    today = pd.Timestamp(now.astimezone(NEW_YORK).date())
    cal = xcals.get_calendar("XNYS")
    latest = cal.date_to_session(today, direction="previous")
    if latest == today and now < cal.session_open(latest):
        latest = cal.previous_session(latest)
    expected_close = latest if now >= cal.session_close(latest) else cal.previous_session(latest)
    with closing(_ro_connection(model_db)) as c:
        account = c.execute("SELECT created_at_utc FROM paper_accounts WHERE account_id=?", (MODEL_2_ACCOUNT_ID,)).fetchone()
    inception = pd.Timestamp(datetime.fromisoformat(account[0]).astimezone(NEW_YORK).date()) if account else today
    offsets = {"1W":pd.DateOffset(weeks=1),"1M":pd.DateOffset(months=1),"3M":pd.DateOffset(months=3)}
    start = today-offsets[period] if period in offsets else pd.Timestamp(year=today.year,month=1,day=1) if period=="YTD" else inception
    start = max(start,inception)
    rows = {}
    if db.exists():
        with closing(_ro_connection(db)) as c:
            tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if period == "1D":
                if "intraday_equity_snapshots" in tables:
                    for day,bucket,stamp,equity,cash,mv in c.execute("""SELECT session_date,bucket_utc,recorded_at_utc,total_equity,cash,market_value FROM intraday_equity_snapshots WHERE account_id=? AND session_date=? ORDER BY bucket_utc""",(MODEL_2_ACCOUNT_ID,str(latest.date()))):
                        rows[bucket]=dict(session=day,equity=_decimal(equity),cash=_decimal(cash),market_value=_decimal(mv),timestamp=stamp,label=datetime.fromisoformat(stamp).astimezone(NEW_YORK).strftime('%H:%M ET'),source="intraday")
            else:
                for table,stamp,source in (("daily_equity_backfill","reconstructed_at_utc","backfill"),("daily_equity_snapshots","recorded_at_utc","verified close")):
                    if table not in tables: continue
                    for day,recorded,equity,cash,mv in c.execute(f"SELECT session_date,{stamp},total_equity,cash,market_value FROM {table} WHERE account_id=? AND session_date BETWEEN ? AND ?",(MODEL_2_ACCOUNT_ID,str(start.date()),str(expected_close.date()))):
                        rows[day]=dict(session=day,equity=_decimal(equity),cash=_decimal(cash),market_value=_decimal(mv),timestamp=recorded,label=day,source=source)
    points=[rows[k] for k in sorted(rows)]
    if period == "1D":
        missing=[]
        message=f"{latest.date()} | {len(points)} saved intraday points; no interpolation."
        if points:
            age=now-datetime.fromisoformat(points[-1]['timestamp'])
            message+=f" Latest recorded {points[-1]['label']}."
            if now < cal.session_close(latest) and age>timedelta(minutes=20): message+=" Snapshot stale."
    else:
        expected=[str(s.date()) for s in cal.sessions_in_range(start,expected_close)] if start<=expected_close else []
        missing=[s for s in expected if s not in rows]
        message=f"{len(points)} saved closing values; {len(missing)} missing session(s)."
        if missing: message+=" Missing: "+", ".join(missing[-5:])
        if points: message+=f" Latest close {points[-1]['session']}."
    return dict(period=period,points=points,missing=missing,message=message)


def equity_history(max_points: int = 40) -> list[dict[str, Any]]:
    return performance_history("ALL")["points"][-max_points:]


def brokerage_snapshot() -> dict[str, Any]:
    snapshot = system_snapshot()
    snapshot["movers"] = market_movers(limit=5)
    snapshot["allocation"] = portfolio_allocation()
    snapshot["performance"] = performance_history("ALL")
    snapshot["equity_history"] = snapshot["performance"]["points"]
    snapshot["candidates"] = candidate_ranking(top_n=5)
    snapshot["recent_fills"] = load_fills(limit=5)
    return snapshot
