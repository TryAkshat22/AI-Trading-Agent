from datetime import (
    date,
    datetime,
    timezone,
)
from types import SimpleNamespace

import pytest

from trading.stale_order_service import (
    MISSED_EXECUTION_WINDOW_CODE,
    MISSED_EXECUTION_WINDOW_REASON,
    StaleOrderSafetyError,
    StaleOrderService,
)


SESSION = date(
    2026,
    9,
    14,
)

MARKET_OPEN = datetime(
    2026,
    9,
    14,
    13,
    30,
    tzinfo=timezone.utc,
)

WINDOW_CLOSE = datetime(
    2026,
    9,
    14,
    13,
    35,
    tzinfo=timezone.utc,
)


class FakeReadinessChecker:

    def __init__(
        self,
        result,
    ):

        self.result = result

        self.calls = []

    def check(
        self,
        execution_session,
    ):

        self.calls.append(
            execution_session
        )

        return self.result


class FakePendingOrderQuery:

    def __init__(
        self,
        order_ids,
    ):

        self.order_ids = list(
            order_ids
        )

        self.calls = []

    def find_order_ids_for_session(
        self,
        execution_session,
    ):

        self.calls.append(
            execution_session
        )

        return list(
            self.order_ids
        )


class FakeTradingStorage:

    def __init__(
        self,
    ):

        self.rejections = []

    def reject_order(
        self,
        order_id,
        rejection_code,
        rejection_reason,
    ):

        self.rejections.append(
            (
                order_id,
                rejection_code,
                rejection_reason,
            )
        )


def readiness(
    *,
    checked_at,
    pending_orders=4,
    clean_orders=4,
    problem_orders=0,
    window_open=False,
):

    return SimpleNamespace(
        execution_session=SESSION,
        market_open_utc=(
            MARKET_OPEN
        ),
        window_close_utc=(
            WINDOW_CLOSE
        ),
        checked_at_utc=(
            checked_at
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
        ready_to_execute=False,
        reason="test",
    )


def build_service(
    readiness_result,
    order_ids=(
        "order-1",
        "order-2",
        "order-3",
        "order-4",
    ),
):

    checker = (
        FakeReadinessChecker(
            readiness_result
        )
    )

    query = (
        FakePendingOrderQuery(
            order_ids
        )
    )

    storage = (
        FakeTradingStorage()
    )

    service = (
        StaleOrderService(
            readiness_checker=(
                checker
            ),
            pending_order_query=(
                query
            ),
            trading_storage=(
                storage
            ),
        )
    )

    return (
        service,
        checker,
        query,
        storage,
    )


def test_expired_window_rejects_orders():

    (
        service,
        checker,
        query,
        storage,
    ) = build_service(
        readiness(
            checked_at=datetime(
                2026,
                9,
                14,
                15,
                52,
                tzinfo=timezone.utc,
            )
        )
    )

    result = (
        service.expire_session(
            SESSION
        )
    )

    assert (
        result.discovered_orders
        == 4
    )

    assert (
        result.rejected_orders
        == 4
    )

    assert (
        result.rejection_code
        == MISSED_EXECUTION_WINDOW_CODE
    )

    assert (
        len(
            storage.rejections
        )
        == 4
    )

    for (
        order_id,
        code,
        reason,
    ) in storage.rejections:

        assert order_id.startswith(
            "order-"
        )

        assert (
            code
            == MISSED_EXECUTION_WINDOW_CODE
        )

        assert (
            reason
            == MISSED_EXECUTION_WINDOW_REASON
        )


def test_no_orders_is_noop():

    (
        service,
        _,
        query,
        storage,
    ) = build_service(
        readiness(
            checked_at=datetime(
                2026,
                9,
                14,
                15,
                52,
                tzinfo=timezone.utc,
            ),
            pending_orders=0,
            clean_orders=0,
        ),
        order_ids=(),
    )

    result = (
        service.expire_session(
            SESSION
        )
    )

    assert (
        result.rejected_orders
        == 0
    )

    assert (
        query.calls
        == []
    )

    assert (
        storage.rejections
        == []
    )


def test_before_market_open_rejected():

    (
        service,
        _,
        _,
        storage,
    ) = build_service(
        readiness(
            checked_at=datetime(
                2026,
                9,
                14,
                13,
                0,
                tzinfo=timezone.utc,
            )
        )
    )

    with pytest.raises(
        StaleOrderSafetyError
    ):

        service.expire_session(
            SESSION
        )

    assert (
        storage.rejections
        == []
    )


def test_open_window_rejected():

    (
        service,
        _,
        _,
        storage,
    ) = build_service(
        readiness(
            checked_at=datetime(
                2026,
                9,
                14,
                13,
                32,
                tzinfo=timezone.utc,
            ),
            window_open=True,
        )
    )

    with pytest.raises(
        StaleOrderSafetyError
    ):

        service.expire_session(
            SESSION
        )

    assert (
        storage.rejections
        == []
    )


def test_problem_orders_prevent_mutation():

    (
        service,
        _,
        query,
        storage,
    ) = build_service(
        readiness(
            checked_at=datetime(
                2026,
                9,
                14,
                15,
                52,
                tzinfo=timezone.utc,
            ),
            clean_orders=3,
            problem_orders=1,
        )
    )

    with pytest.raises(
        StaleOrderSafetyError
    ):

        service.expire_session(
            SESSION
        )

    assert (
        query.calls
        == []
    )

    assert (
        storage.rejections
        == []
    )


def test_count_change_prevents_mutation():

    (
        service,
        _,
        _,
        storage,
    ) = build_service(
        readiness(
            checked_at=datetime(
                2026,
                9,
                14,
                15,
                52,
                tzinfo=timezone.utc,
            ),
            pending_orders=4,
        ),
        order_ids=(
            "order-1",
            "order-2",
            "order-3",
        ),
    )

    with pytest.raises(
        StaleOrderSafetyError
    ):

        service.expire_session(
            SESSION
        )

    assert (
        storage.rejections
        == []
    )