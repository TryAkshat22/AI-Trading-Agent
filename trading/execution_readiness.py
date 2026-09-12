from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Callable
from zoneinfo import ZoneInfo

import pandas_market_calendars as mcal

from audit_pending_orders import (
    PendingOrderAuditResult,
    PendingOrderAuditor,
)


NEW_YORK = ZoneInfo(
    "America/New_York"
)


class ExecutionReadinessError(Exception):
    """
    Base error for execution-readiness checks.
    """


class InvalidReadinessSessionError(
    ExecutionReadinessError
):
    """
    Requested date is not a valid NYSE session.
    """


@dataclass(frozen=True)
class ExecutionReadinessResult:

    execution_session: date

    market_open_utc: datetime
    window_close_utc: datetime
    checked_at_utc: datetime

    pending_orders: int
    clean_orders: int
    problem_orders: int

    session_valid: bool
    execution_window_open: bool
    ready_to_execute: bool

    reason: str

    @property
    def market_open_et(
        self,
    ) -> datetime:

        return (
            self.market_open_utc
            .astimezone(
                NEW_YORK
            )
        )

    @property
    def window_close_et(
        self,
    ) -> datetime:

        return (
            self.window_close_utc
            .astimezone(
                NEW_YORK
            )
        )

    @property
    def checked_at_et(
        self,
    ) -> datetime:

        return (
            self.checked_at_utc
            .astimezone(
                NEW_YORK
            )
        )


class ExecutionReadinessChecker:
    """
    Read-only pre-execution safety check.

    This checker does NOT:
        - fetch market prices
        - create execution observations
        - create attempts
        - create fills
        - reject orders
        - modify order status

    It verifies:
        1. requested date is a valid NYSE session
        2. PENDING orders exist
        3. all discovered orders pass the audit
        4. current time is within the allowed
           near-open execution window
    """

    def __init__(
        self,
        auditor: PendingOrderAuditor | None = None,
        calendar_name: str = "NYSE",
        max_execution_delay: timedelta = timedelta(
            minutes=5
        ),
        clock: Callable[
            [],
            datetime,
        ] | None = None,
    ) -> None:

        if max_execution_delay <= timedelta(0):

            raise ValueError(
                "max_execution_delay must "
                "be positive."
            )

        self.auditor = (
            auditor
            if auditor is not None
            else PendingOrderAuditor()
        )

        self.calendar_name = (
            calendar_name
        )

        self.calendar = (
            mcal.get_calendar(
                calendar_name
            )
        )

        self.max_execution_delay = (
            max_execution_delay
        )

        self.clock = (
            clock
            if clock is not None
            else self._utc_now
        )

    @staticmethod
    def _utc_now() -> datetime:

        return datetime.now(
            timezone.utc
        )

    def _get_market_open(
        self,
        execution_session: date,
    ) -> datetime:

        schedule = (
            self.calendar.schedule(
                start_date=execution_session,
                end_date=execution_session,
            )
        )

        if schedule.empty:

            raise InvalidReadinessSessionError(
                f"{execution_session} is not "
                f"a valid {self.calendar_name} "
                "trading session."
            )

        market_open = (
            schedule.iloc[0][
                "market_open"
            ]
        )

        if hasattr(
            market_open,
            "to_pydatetime",
        ):

            market_open = (
                market_open
                .to_pydatetime()
            )

        if market_open.tzinfo is None:

            raise ExecutionReadinessError(
                "Calendar returned a naive "
                "market-open timestamp."
            )

        return (
            market_open
            .astimezone(
                timezone.utc
            )
        )

    def check(
        self,
        execution_session: date,
    ) -> ExecutionReadinessResult:

        if not isinstance(
            execution_session,
            date,
        ):

            raise TypeError(
                "execution_session must be "
                "a datetime.date."
            )

        market_open_utc = (
            self._get_market_open(
                execution_session
            )
        )

        window_close_utc = (
            market_open_utc
            + self.max_execution_delay
        )

        checked_at_utc = (
            self.clock()
        )

        if (
            checked_at_utc.tzinfo
            is None
        ):

            raise ExecutionReadinessError(
                "Readiness clock must return "
                "a timezone-aware datetime."
            )

        checked_at_utc = (
            checked_at_utc
            .astimezone(
                timezone.utc
            )
        )

        audit = (
            self.auditor
            .audit_session(
                execution_session
            )
        )

        pending_orders = (
            audit.total_orders
        )

        clean_orders = (
            audit.clean_orders
        )

        problem_orders = (
            len(
                audit.problem_orders
            )
        )

        window_open = (
            market_open_utc
            <= checked_at_utc
            <= window_close_utc
        )

        if pending_orders == 0:

            ready = False

            reason = (
                "No PENDING orders are scheduled "
                "for this execution session."
            )

        elif problem_orders > 0:

            ready = False

            reason = (
                f"{problem_orders} PENDING order(s) "
                "failed the pre-execution audit."
            )

        elif checked_at_utc < market_open_utc:

            ready = False

            reason = (
                "Execution session has not "
                "opened yet."
            )

        elif checked_at_utc > window_close_utc:

            ready = False

            reason = (
                "The allowed near-open execution "
                "window has expired."
            )

        else:

            ready = True

            reason = (
                "All PENDING orders are clean "
                "and the execution window is open."
            )

        return ExecutionReadinessResult(
            execution_session=(
                execution_session
            ),
            market_open_utc=(
                market_open_utc
            ),
            window_close_utc=(
                window_close_utc
            ),
            checked_at_utc=(
                checked_at_utc
            ),
            pending_orders=(
                pending_orders
            ),
            clean_orders=(
                clean_orders
            ),
            problem_orders=(
                problem_orders
            ),
            session_valid=True,
            execution_window_open=(
                window_open
            ),
            ready_to_execute=(
                ready
            ),
            reason=(
                reason
            ),
        )


def print_readiness(
    result: ExecutionReadinessResult,
) -> None:

    print()
    print(
        "Execution Readiness Check"
    )

    print(
        "========================="
    )

    print(
        f"Session: "
        f"{result.execution_session}"
    )

    print(
        "NYSE session: VALID"
    )

    print(
        f"Market open: "
        f"{result.market_open_et.strftime('%I:%M:%S %p %Z')}"
    )

    print(
        f"Window closes: "
        f"{result.window_close_et.strftime('%I:%M:%S %p %Z')}"
    )

    print(
        f"Current time: "
        f"{result.checked_at_et.strftime('%Y-%m-%d %I:%M:%S %p %Z')}"
    )

    print()

    print(
        f"Pending orders: "
        f"{result.pending_orders}"
    )

    print(
        f"Clean orders: "
        f"{result.clean_orders}"
    )

    print(
        f"Problem orders: "
        f"{result.problem_orders}"
    )

    print()

    print(
        "Execution window: "
        + (
            "OPEN"
            if result.execution_window_open
            else "CLOSED"
        )
    )

    print(
        "READY TO EXECUTE: "
        + (
            "YES"
            if result.ready_to_execute
            else "NO"
        )
    )

    print(
        f"Reason: "
        f"{result.reason}"
    )