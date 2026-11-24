
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import pandas as pd

from model2_config import MODEL_2_VERSION
from model2_decision_ledger import (
    Model2DecisionLedger,
)
from model2_decision_runner import (
    build_model2_decision_components,
)


NEW_YORK = ZoneInfo("America/New_York")


class Model2DecisionCommandError(RuntimeError):
    """A Model 2 decision run did not pass its safeguards."""


def check_after_close(now: datetime) -> str:
    """
    Return the decision session as YYYY-MM-DD.

    Respect NYSE holidays and scheduled early closes.
    """
    if (
        not isinstance(now, datetime)
        or now.tzinfo is None
        or now.utcoffset() is None
    ):
        raise Model2DecisionCommandError(
            "The decision time must be timezone-aware."
        )

    now_utc = now.astimezone(timezone.utc)
    local_date = now_utc.astimezone(NEW_YORK).date()

    calendar = xcals.get_calendar("XNYS")
    session = pd.Timestamp(local_date)

    if not calendar.is_session(session):
        raise Model2DecisionCommandError(
            f"{local_date} is not an NYSE trading session."
        )

    close_utc = (
        calendar.session_close(session)
        .to_pydatetime()
        .astimezone(timezone.utc)
    )

    earliest_run = close_utc + timedelta(minutes=15)

    if now_utc < earliest_run:
        raise Model2DecisionCommandError(
            "Too early for an after-close decision. "
            "Earliest permitted time: "
            f"{earliest_run.astimezone(NEW_YORK).isoformat()}."
        )

    return local_date.isoformat()


def order_id_for(
    decision_session: str,
    ticker: str,
) -> str:
    return (
        f"{MODEL_2_VERSION}-"
        f"{decision_session}-"
        f"{ticker.strip().upper()}"
    )


def _existing_ledger_status(
    database_path: Path,
    decision_session: str,
) -> str | None:
    """
    Inspect an existing ledger without creating a table
    or modifying the database.

    A missing ledger table is normal before the first
    explicitly authorized decision run.
    """
    database_path = Path(database_path).resolve()

    if not database_path.is_file():
        raise Model2DecisionCommandError(
            "Model 2 database is missing."
        )

    uri = database_path.as_uri() + "?mode=ro"

    with sqlite3.connect(
        uri,
        uri=True,
        timeout=10,
    ) as connection:
        table = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND name = 'model2_decision_runs'
            """
        ).fetchone()

        if table is None:
            return None

        row = connection.execute(
            """
            SELECT status
            FROM model2_decision_runs
            WHERE decision_session = ?
              AND model_version = ?
            """,
            (
                decision_session,
                MODEL_2_VERSION,
            ),
        ).fetchone()

    return row[0] if row is not None else None


def _count_session_orders(
    trading_storage,
    decision_session: str,
    tickers: tuple[str, ...],
) -> int:
    """
    Count deterministic order IDs for this run.

    This count is used when recording a failure after
    the batch may have saved some orders.
    """
    return sum(
        trading_storage.order_exists(
            order_id_for(decision_session, ticker)
        )
        for ticker in tickers
    )


def run_model2_decision(
    *,
    execute: bool = False,
    now: datetime | None = None,
):
    """
    Readiness-only by default.

    execute=True may save Model 2 decision snapshots
    and PENDING orders. It never executes fills.

    A durable ledger claim is required before the
    decision batch begins.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    decision_session = check_after_close(now)
    session_date = date.fromisoformat(decision_session)

    components = build_model2_decision_components()
    context = components.context

    if context.model_version != MODEL_2_VERSION:
        raise Model2DecisionCommandError(
            "Unexpected Model 2 version."
        )

    if (
        Path(context.database_path).resolve()
        == Path(context.observation_database_path).resolve()
    ):
        raise Model2DecisionCommandError(
            "Model 2 trading database must be separate "
            "from its observation database."
        )

    tickers = tuple(components.batch_runner.tickers)

    existing_orders = [
        order_id_for(decision_session, ticker)
        for ticker in tickers
        if context.trading_storage.order_exists(
            order_id_for(decision_session, ticker)
        )
    ]

    if existing_orders:
        raise Model2DecisionCommandError(
            "At least one Model 2 order already exists "
            f"for {decision_session}. "
            "Inspect that decision run before retrying. "
            f"First existing order: {existing_orders[0]}"
        )

    ledger_status = _existing_ledger_status(
        context.database_path,
        decision_session,
    )

    if ledger_status is not None:
        raise Model2DecisionCommandError(
            "This Model 2 decision session already has "
            f"a {ledger_status} ledger record. "
            "Inspect it before retrying."
        )

    if not execute:
        print("Model 2 decision readiness: PASS")
        print(f"Decision session: {decision_session}")
        print(f"Account: {context.account_id}")
        print(f"Trading database: {context.database_path}")
        print(
            "No prices were downloaded and "
            "no decisions or orders were created."
        )
        return None

    # Preflight all tickers before claiming the session.
    # A preflight failure leaves no ledger claim and
    # creates no decision snapshots or orders.
    market_results = {}
    market_prices = {}

    for ticker in tickers:
        result = components.batch_runner.market_data_fetcher(
            ticker
        )

        quality = (
            components.batch_runner.quality_report_builder(
                result
            )
        )

        if result.ticker.strip().upper() != ticker:
            raise Model2DecisionCommandError(
                f"Wrong market-data ticker for {ticker}."
            )

        if quality.ticker.strip().upper() != ticker:
            raise Model2DecisionCommandError(
                f"Wrong quality-report ticker for {ticker}."
            )

        if not quality.safe_to_use:
            raise Model2DecisionCommandError(
                f"Daily market data failed quality "
                f"checks for {ticker}."
            )

        if (
            quality.latest_data_session != session_date
            or quality.latest_expected_completed_session
            != session_date
        ):
            raise Model2DecisionCommandError(
                f"{ticker} does not have confirmed "
                "completed-session data for "
                f"{decision_session}."
            )

        if (
            result.data.empty
            or "Close" not in result.data.columns
        ):
            raise Model2DecisionCommandError(
                f"{ticker} has no daily close."
            )

        price = Decimal(
            str(result.data["Close"].iloc[-1])
        )

        if not price.is_finite() or price <= 0:
            raise Model2DecisionCommandError(
                f"{ticker} has an invalid daily close."
            )

        market_results[ticker] = result
        market_prices[ticker] = price

    # Only preflighted data may enter the batch.
    components.batch_runner.market_data_fetcher = (
        lambda ticker: market_results[ticker]
    )

    ledger = Model2DecisionLedger(
        database_path=context.database_path
    )
    ledger.initialize()

    # Database uniqueness makes this claim atomic:
    # two simultaneous commands cannot both proceed.
    claim = ledger.claim(
        decision_session=session_date,
        started_at=now,
    )

    result = None

    try:
        result = components.decision_runner.run(
            decision_timestamp=now,
            market_prices=market_prices,
            order_id_factory=lambda ticker: order_id_for(
                decision_session,
                ticker,
            ),
        )

        print("Model 2 decision run finished")
        print("=============================")
        print(f"Decision session: {decision_session}")
        print(f"Ledger run ID: {claim.run_id}")
        print(f"Tickers: {result.total_tickers}")
        print(f"Successful: {result.successful_tickers}")
        print(f"Failed: {result.failed_tickers}")
        print(
            f"Pending orders created: "
            f"{result.orders_created}"
        )

        for failure in result.batch_result.failures:
            print(
                f"FAILED {failure.ticker}: "
                f"{failure.error_type}: "
                f"{failure.error_message}"
            )

        if result.had_failures:
            raise Model2DecisionCommandError(
                "One or more ticker decisions failed. "
                "Inspect persisted results before any retry."
            )

        ledger.finish(
            claim.run_id,
            status="COMPLETED",
            finished_at=datetime.now(timezone.utc),
            orders_created=result.orders_created,
            failed_tickers=0,
        )

        return result

    except Exception as exc:
        # A failure may occur after earlier tickers have
        # persisted orders. Record what actually exists.
        saved_order_count = _count_session_orders(
            context.trading_storage,
            decision_session,
            tickers,
        )

        failed_count = (
            result.failed_tickers
            if result is not None
            else 1
        )

        # A failure to finalize must remain visible.
        # Do not silently claim that the ledger is FAILED
        # if its update did not persist.
        ledger.finish(
            claim.run_id,
            status="FAILED",
            finished_at=datetime.now(timezone.utc),
            orders_created=saved_order_count,
            failed_tickers=max(1, failed_count),
            error_message=(
                f"{type(exc).__name__}: {exc}"
            ),
        )

        raise


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Guarded Model 2 after-close decision command."
        )
    )

    parser.add_argument(
        "--run",
        action="store_true",
        help=(
            "Explicitly run decisions; may create "
            "pending Model 2 orders."
        ),
    )

    args = parser.parse_args()

    try:
        run_model2_decision(execute=args.run)
        return 0

    except Exception as exc:
        print(
            "Model 2 decision blocked: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())