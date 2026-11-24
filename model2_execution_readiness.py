from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import pandas as pd

from model2_config import (
    MODEL_2_ACCOUNT_ID,
    MODEL_2_VERSION,
    get_model2_paths,
)
from trading.flexible_observation_selector import (
    FlexibleObservationSelector,
)
from trading.flexible_order_eligibility import (
    FlexibleOrderEligibilityChecker,
)


NEW_YORK = ZoneInfo("America/New_York")


class Model2ExecutionReadinessError(RuntimeError):
    """Model 2 execution readiness cannot be established."""


def check_execution_window(
    execution_session: date,
    now: datetime,
) -> None:
    """
    Validate the actual time of a proposed Model 2
    execution check.

    Flexible same-day window:
      - starts 15 minutes after the NYSE open
      - ends 30 minutes before the scheduled NYSE close

    The actual exchange calendar is used, so early-close
    sessions automatically receive a shorter window.
    """
    if (
        not isinstance(execution_session, date)
        or isinstance(execution_session, datetime)
    ):
        raise Model2ExecutionReadinessError(
            "execution_session must be a date."
        )

    if (
        not isinstance(now, datetime)
        or now.tzinfo is None
        or now.utcoffset() is None
    ):
        raise Model2ExecutionReadinessError(
            "now must be a timezone-aware datetime."
        )

    now_utc = now.astimezone(timezone.utc)

    if (
        now_utc.astimezone(NEW_YORK).date()
        != execution_session
    ):
        raise Model2ExecutionReadinessError(
            "Execution session must match today's "
            "New York calendar date."
        )

    calendar = xcals.get_calendar("XNYS")
    session = pd.Timestamp(execution_session)

    if not calendar.is_session(session):
        raise Model2ExecutionReadinessError(
            f"{execution_session} is not an NYSE session."
        )

    market_open = (
        calendar.session_open(session)
        .to_pydatetime()
        .astimezone(timezone.utc)
    )

    market_close = (
        calendar.session_close(session)
        .to_pydatetime()
        .astimezone(timezone.utc)
    )

    window_start = (
        market_open
        + timedelta(minutes=15)
    )

    window_end = (
        market_close
        - timedelta(minutes=30)
    )

    if window_end <= window_start:
        raise Model2ExecutionReadinessError(
            "NYSE session is too short to provide "
            "a valid Model 2 execution window."
        )

    if not (
        window_start
        <= now_utc
        < window_end
    ):
        raise Model2ExecutionReadinessError(
            "Outside the Model 2 execution window. "
            f"Window: "
            f"{window_start.astimezone(NEW_YORK).isoformat()} "
            f"to "
            f"{window_end.astimezone(NEW_YORK).isoformat()} "
            "(end exclusive)."
        )


def inspect_model2_execution(
    *,
    execution_session: date,
    now: datetime | None = None,
):
    """
    Inspect eligibility without executing any order.

    Trading records: Model 2 database.
    Intraday observations: original database.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    check_execution_window(
        execution_session,
        now,
    )

    paths = get_model2_paths()

    trading_database = Path(
        paths.model2_database
    ).resolve()

    observation_database = Path(
        paths.observation_database
    ).resolve()

    if trading_database == observation_database:
        raise Model2ExecutionReadinessError(
            "Trading and observation databases "
            "must be separate."
        )

    if not trading_database.is_file():
        raise Model2ExecutionReadinessError(
            "Model 2 trading database is missing."
        )

    if not observation_database.is_file():
        raise Model2ExecutionReadinessError(
            "Intraday observation database is missing."
        )

    selector = FlexibleObservationSelector(
        database_path=observation_database,
    )

    checker = FlexibleOrderEligibilityChecker(
        database_path=trading_database,
        observation_selector=selector,
        expected_model_version=MODEL_2_VERSION,
    )

    result = checker.check(
        execution_session=execution_session,
        checked_at=now,
    )

    print(
        "Model 2 execution inspection — NO TRADES"
    )
    print(
        "========================================"
    )
    print(
        f"Account: {MODEL_2_ACCOUNT_ID}"
    )
    print(
        f"Session: {execution_session}"
    )
    print(
        f"Trading database: {trading_database}"
    )
    print(
        f"Observation database: "
        f"{observation_database}"
    )
    print(
        f"Eligible orders: {result.eligible_count}"
    )
    print(
        f"Ineligible orders: "
        f"{result.ineligible_count}"
    )
    print()

    for order in result.eligible_orders:
        print(
            f"ELIGIBLE {order.ticker} | "
            f"{order.order_id}"
        )
        print(
            f"  Observed {order.price_field}: "
            f"${order.reference_price}"
        )
        print(
            "  Bar start (UTC): "
            f"{order.observation_bar_start_utc}"
        )
        print(
            "  Retrieved (UTC): "
            f"{order.observation_retrieved_at_utc}"
        )

    for order in result.ineligible_orders:
        print(
            f"INELIGIBLE {order.ticker} | "
            f"{order.order_id}"
        )
        print(
            f"  Reason: {order.reason}"
        )

    print()
    print(
        "Inspection only. No orders were executed "
        "or fills created."
    )

    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only Model 2 execution inspection."
        )
    )

    parser.add_argument(
        "--session",
        required=True,
        type=date.fromisoformat,
        help="Execution session: YYYY-MM-DD.",
    )

    args = parser.parse_args()

    try:
        inspect_model2_execution(
            execution_session=args.session,
        )

        return 0

    except Exception as exc:
        print(
            "Model 2 execution inspection blocked: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )

        return 1


if __name__ == "__main__":
    raise SystemExit(main())