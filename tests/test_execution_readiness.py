from __future__ import annotations

from dataclasses import dataclass
from datetime import (
    date,
    datetime,
    timezone,
)

import pytest

from trading.execution_readiness import (
    ExecutionReadinessChecker,
    ExecutionReadinessError,
    InvalidReadinessSessionError,
)


SESSION = date(
    2026,
    9,
    14,
)


@dataclass(frozen=True)
class FakeProblemOrder:
    order_id: str


class FakeAuditResult:

    def __init__(
        self,
        total_orders: int,
        clean_orders: int,
    ) -> None:

        self.total_orders = (
            total_orders
        )

        self.clean_orders = (
            clean_orders
        )

        problem_count = (
            total_orders
            - clean_orders
        )

        self.problem_orders = tuple(
            FakeProblemOrder(
                order_id=f"problem-{index}"
            )
            for index in range(
                problem_count
            )
        )


class FakeAuditor:

    def __init__(
        self,
        total_orders: int = 4,
        clean_orders: int = 4,
    ) -> None:

        self.total_orders = (
            total_orders
        )

        self.clean_orders = (
            clean_orders
        )

        self.sessions = []

    def audit_session(
        self,
        execution_session,
    ):

        self.sessions.append(
            execution_session
        )

        return FakeAuditResult(
            total_orders=(
                self.total_orders
            ),
            clean_orders=(
                self.clean_orders
            ),
        )


def clock_at(
    hour: int,
    minute: int,
    second: int = 0,
):

    def clock():

        return datetime(
            2026,
            9,
            14,
            hour,
            minute,
            second,
            tzinfo=timezone.utc,
        )

    return clock


def test_ready_inside_execution_window():

    checker = (
        ExecutionReadinessChecker(
            auditor=FakeAuditor(),
            clock=clock_at(
                13,
                31,
            ),
        )
    )

    result = (
        checker.check(
            SESSION
        )
    )

    assert (
        result.pending_orders
        == 4
    )

    assert (
        result.clean_orders
        == 4
    )

    assert (
        result.problem_orders
        == 0
    )

    assert (
        result.execution_window_open
        is True
    )

    assert (
        result.ready_to_execute
        is True
    )


def test_market_open_boundary_is_allowed():

    checker = (
        ExecutionReadinessChecker(
            auditor=FakeAuditor(),
            clock=clock_at(
                13,
                30,
            ),
        )
    )

    result = (
        checker.check(
            SESSION
        )
    )

    assert (
        result.ready_to_execute
        is True
    )


def test_five_minute_boundary_is_allowed():

    checker = (
        ExecutionReadinessChecker(
            auditor=FakeAuditor(),
            clock=clock_at(
                13,
                35,
            ),
        )
    )

    result = (
        checker.check(
            SESSION
        )
    )

    assert (
        result.ready_to_execute
        is True
    )


def test_before_open_is_not_ready():

    checker = (
        ExecutionReadinessChecker(
            auditor=FakeAuditor(),
            clock=clock_at(
                13,
                29,
                59,
            ),
        )
    )

    result = (
        checker.check(
            SESSION
        )
    )

    assert (
        result.execution_window_open
        is False
    )

    assert (
        result.ready_to_execute
        is False
    )

    assert (
        result.reason
        == (
            "Execution session has not "
            "opened yet."
        )
    )


def test_after_window_is_not_ready():

    checker = (
        ExecutionReadinessChecker(
            auditor=FakeAuditor(),
            clock=clock_at(
                13,
                35,
                1,
            ),
        )
    )

    result = (
        checker.check(
            SESSION
        )
    )

    assert (
        result.execution_window_open
        is False
    )

    assert (
        result.ready_to_execute
        is False
    )

    assert (
        result.reason
        == (
            "The allowed near-open execution "
            "window has expired."
        )
    )


def test_problem_order_blocks_execution():

    checker = (
        ExecutionReadinessChecker(
            auditor=FakeAuditor(
                total_orders=4,
                clean_orders=3,
            ),
            clock=clock_at(
                13,
                31,
            ),
        )
    )

    result = (
        checker.check(
            SESSION
        )
    )

    assert (
        result.problem_orders
        == 1
    )

    assert (
        result.ready_to_execute
        is False
    )


def test_no_orders_is_not_ready():

    checker = (
        ExecutionReadinessChecker(
            auditor=FakeAuditor(
                total_orders=0,
                clean_orders=0,
            ),
            clock=clock_at(
                13,
                31,
            ),
        )
    )

    result = (
        checker.check(
            SESSION
        )
    )

    assert (
        result.pending_orders
        == 0
    )

    assert (
        result.ready_to_execute
        is False
    )


def test_weekend_is_invalid_session():

    checker = (
        ExecutionReadinessChecker(
            auditor=FakeAuditor(),
            clock=clock_at(
                13,
                31,
            ),
        )
    )

    with pytest.raises(
        InvalidReadinessSessionError
    ):

        checker.check(
            date(
                2026,
                9,
                12,
            )
        )


def test_naive_clock_is_rejected():

    def naive_clock():

        return datetime(
            2026,
            9,
            14,
            13,
            31,
        )

    checker = (
        ExecutionReadinessChecker(
            auditor=FakeAuditor(),
            clock=naive_clock,
        )
    )

    with pytest.raises(
        ExecutionReadinessError
    ):

        checker.check(
            SESSION
        )


def test_auditor_receives_requested_session():

    auditor = (
        FakeAuditor()
    )

    checker = (
        ExecutionReadinessChecker(
            auditor=auditor,
            clock=clock_at(
                13,
                31,
            ),
        )
    )

    checker.check(
        SESSION
    )

    assert (
        auditor.sessions
        == [
            SESSION
        ]
    )