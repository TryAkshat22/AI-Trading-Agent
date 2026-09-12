from __future__ import annotations

from datetime import (
    date,
    datetime,
    timezone,
)

import pytest

from database.pending_order_query import (
    InvalidPendingOrderSessionError,
    PendingOrderQuery,
)
from database.trading_storage import (
    TradingStorage,
)
from trading.orders import (
    Order,
    OrderSide,
)


TARGET_SESSION = date(
    2026,
    9,
    8,
)


def make_order(
    *,
    order_id: str,
    ticker: str,
    execution_session: date = TARGET_SESSION,
) -> Order:

    return Order(
        order_id=order_id,
        ticker=ticker,
        side=OrderSide.BUY,
        quantity=5,
        signal_timestamp_utc=datetime(
            2026,
            9,
            4,
            21,
            0,
            tzinfo=timezone.utc,
        ),
        execution_session=(
            execution_session
        ),
    )


def make_storage(
    tmp_path,
):

    database_path = (
        tmp_path
        / "test.db"
    )

    trades = TradingStorage(
        database_path
    )

    trades.initialize()

    query = PendingOrderQuery(
        database_path
    )

    return (
        trades,
        query,
    )


def test_pending_order_for_session_is_found(
    tmp_path,
):

    trades, query = (
        make_storage(
            tmp_path
        )
    )

    trades.save_order(
        make_order(
            order_id="order-1",
            ticker="AAPL",
        ),
        model_version="model-1",
    )

    results = (
        query.find_for_session(
            TARGET_SESSION
        )
    )

    assert len(results) == 1

    assert (
        results[0].order_id
        == "order-1"
    )

    assert (
        results[0].ticker
        == "AAPL"
    )

    assert (
        results[0].execution_session
        == TARGET_SESSION
    )

    assert (
        results[0].model_version
        == "model-1"
    )


def test_multiple_pending_orders_are_found(
    tmp_path,
):

    trades, query = (
        make_storage(
            tmp_path
        )
    )

    trades.save_order(
        make_order(
            order_id="aapl-order",
            ticker="AAPL",
        )
    )

    trades.save_order(
        make_order(
            order_id="msft-order",
            ticker="MSFT",
        )
    )

    trades.save_order(
        make_order(
            order_id="nvda-order",
            ticker="NVDA",
        )
    )

    results = (
        query.find_for_session(
            TARGET_SESSION
        )
    )

    assert (
        len(results)
        == 3
    )

    assert (
        {
            result.order_id
            for result in results
        }
        == {
            "aapl-order",
            "msft-order",
            "nvda-order",
        }
    )


def test_wrong_session_is_not_returned(
    tmp_path,
):

    trades, query = (
        make_storage(
            tmp_path
        )
    )

    trades.save_order(
        make_order(
            order_id="today-order",
            ticker="AAPL",
            execution_session=(
                TARGET_SESSION
            ),
        )
    )

    trades.save_order(
        make_order(
            order_id="future-order",
            ticker="MSFT",
            execution_session=date(
                2026,
                9,
                9,
            ),
        )
    )

    results = (
        query.find_for_session(
            TARGET_SESSION
        )
    )

    assert (
        len(results)
        == 1
    )

    assert (
        results[0].order_id
        == "today-order"
    )


def test_rejected_order_is_not_returned(
    tmp_path,
):

    trades, query = (
        make_storage(
            tmp_path
        )
    )

    trades.save_order(
        make_order(
            order_id="pending-order",
            ticker="AAPL",
        )
    )

    trades.save_order(
        make_order(
            order_id="rejected-order",
            ticker="MSFT",
        )
    )

    trades.reject_order(
        order_id="rejected-order",
        rejection_code="TEST_REJECTION",
        rejection_reason=(
            "Test rejection."
        ),
    )

    results = (
        query.find_for_session(
            TARGET_SESSION
        )
    )

    assert (
        len(results)
        == 1
    )

    assert (
        results[0].order_id
        == "pending-order"
    )


def test_order_ids_convenience_method(
    tmp_path,
):

    trades, query = (
        make_storage(
            tmp_path
        )
    )

    trades.save_order(
        make_order(
            order_id="order-1",
            ticker="AAPL",
        )
    )

    trades.save_order(
        make_order(
            order_id="order-2",
            ticker="MSFT",
        )
    )

    order_ids = (
        query.find_order_ids_for_session(
            TARGET_SESSION
        )
    )

    assert (
        set(
            order_ids
        )
        == {
            "order-1",
            "order-2",
        }
    )


def test_count_for_session(
    tmp_path,
):

    trades, query = (
        make_storage(
            tmp_path
        )
    )

    trades.save_order(
        make_order(
            order_id="order-1",
            ticker="AAPL",
        )
    )

    trades.save_order(
        make_order(
            order_id="order-2",
            ticker="MSFT",
        )
    )

    assert (
        query.count_for_session(
            TARGET_SESSION
        )
        == 2
    )


def test_no_pending_orders_returns_empty_tuple(
    tmp_path,
):

    _, query = (
        make_storage(
            tmp_path
        )
    )

    results = (
        query.find_for_session(
            TARGET_SESSION
        )
    )

    assert results == ()


def test_invalid_session_is_rejected(
    tmp_path,
):

    _, query = (
        make_storage(
            tmp_path
        )
    )

    with pytest.raises(
        InvalidPendingOrderSessionError
    ):

        query.find_for_session(
            "2026-09-08"
        )