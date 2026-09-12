from datetime import date, datetime, timezone
from decimal import Decimal
from database.trading_storage import (
    InvalidStoredOrderStateError,
)
import pytest

from database.trading_storage import (
    DuplicateStoredOrderError,
    StoredOrderNotFoundError,
    TradingStorage,
)
from trading.orders import (
    Fill,
    Order,
    OrderSide,
    OrderStatus,
)
from trading.portfolio import (
    Portfolio,
    money,
)


def make_order(
    order_id="order-1",
):

    return Order(
        order_id=order_id,
        ticker="AAPL",
        side=OrderSide.BUY,
        quantity=10,
        signal_timestamp_utc=datetime(
            2026,
            9,
            4,
            21,
            0,
            tzinfo=timezone.utc,
        ),
        execution_session=date(
            2026,
            9,
            8,
        ),
    )


def make_fill(
    order_id="order-1",
):

    return Fill(
        order_id=order_id,
        ticker="AAPL",
        side=OrderSide.BUY,
        quantity=10,
        reference_price=money(100),
        fill_price=money(100.10),
        gross_value=money(1001),
        fees=money(0),
        slippage_cost=money(1),
        execution_session=date(
            2026,
            9,
            8,
        ),
        status=OrderStatus.FILLED,
        realized_pnl=money(0),
    )


def test_order_is_saved(
    tmp_path,
):

    storage = TradingStorage(
        tmp_path / "test.db"
    )

    storage.initialize()

    storage.save_order(
        make_order()
    )

    assert storage.count_orders() == 1

    assert storage.order_exists(
        "order-1"
    )

    assert (
        storage.get_order_status(
            "order-1"
        )
        == "PENDING"
    )


def test_duplicate_order_is_rejected(
    tmp_path,
):

    storage = TradingStorage(
        tmp_path / "test.db"
    )

    storage.initialize()

    order = make_order()

    storage.save_order(order)

    with pytest.raises(
        DuplicateStoredOrderError
    ):
        storage.save_order(order)

    assert storage.count_orders() == 1


def test_fill_updates_order_status(
    tmp_path,
):

    storage = TradingStorage(
        tmp_path / "test.db"
    )

    storage.initialize()

    storage.save_order(
        make_order()
    )

    storage.save_fill(
        make_fill()
    )

    assert storage.count_fills() == 1

    assert (
        storage.get_order_status(
            "order-1"
        )
        == "FILLED"
    )


def test_fill_without_order_is_rejected(
    tmp_path,
):

    storage = TradingStorage(
        tmp_path / "test.db"
    )

    storage.initialize()

    with pytest.raises(
        StoredOrderNotFoundError
    ):
        storage.save_fill(
            make_fill()
        )

    assert storage.count_fills() == 0


def test_duplicate_fill_is_rejected(
    tmp_path,
):

    storage = TradingStorage(
        tmp_path / "test.db"
    )

    storage.initialize()

    storage.save_order(
        make_order()
    )

    fill = make_fill()

    storage.save_fill(fill)

    with pytest.raises(
        DuplicateStoredOrderError
    ):
        storage.save_fill(fill)

    assert storage.count_fills() == 1


def test_portfolio_snapshot_is_saved(
    tmp_path,
):

    storage = TradingStorage(
        tmp_path / "test.db"
    )

    storage.initialize()

    portfolio = Portfolio(
        10_000
    )

    portfolio.buy(
        ticker="AAPL",
        quantity=10,
        price=100,
    )

    storage.save_portfolio_snapshot(
        portfolio=portfolio,
        prices={
            "AAPL": 110,
        },
        session_date=date(
            2026,
            9,
            8,
        ),
        recorded_at_utc=datetime(
            2026,
            9,
            8,
            21,
            0,
            tzinfo=timezone.utc,
        ),
    )

    assert (
        storage.count_portfolio_snapshots()
        == 1
    )

def test_pending_order_can_be_rejected(
    tmp_path,
):

    storage = TradingStorage(
        tmp_path / "test.db"
    )

    storage.initialize()

    storage.save_order(
        make_order()
    )

    rejection = storage.reject_order(
        order_id="order-1",
        rejection_code=(
            "POSITION_LIMIT_EXCEEDED"
        ),
        rejection_reason=(
            "Opening gap caused position "
            "allocation to exceed limit."
        ),
    )

    assert (
        storage.get_order_status(
            "order-1"
        )
        == "REJECTED"
    )

    assert (
        rejection.rejection_code
        == "POSITION_LIMIT_EXCEEDED"
    )

    stored = storage.get_order_rejection(
        "order-1"
    )

    assert stored is not None

    assert (
        stored.rejection_reason
        == (
            "Opening gap caused position "
            "allocation to exceed limit."
        )
    )


def test_filled_order_cannot_be_rejected(
    tmp_path,
):

    storage = TradingStorage(
        tmp_path / "test.db"
    )

    storage.initialize()

    storage.save_order(
        make_order()
    )

    storage.save_fill(
        make_fill()
    )

    with pytest.raises(
        InvalidStoredOrderStateError
    ):
        storage.reject_order(
            order_id="order-1",
            rejection_code="TEST",
            rejection_reason="Should fail.",
        )

    assert (
        storage.get_order_status(
            "order-1"
        )
        == "FILLED"
    )


def test_rejected_order_cannot_be_rejected_twice(
    tmp_path,
):

    storage = TradingStorage(
        tmp_path / "test.db"
    )

    storage.initialize()

    storage.save_order(
        make_order()
    )

    storage.reject_order(
        order_id="order-1",
        rejection_code="TEST",
        rejection_reason="First rejection.",
    )

    with pytest.raises(
        InvalidStoredOrderStateError
    ):
        storage.reject_order(
            order_id="order-1",
            rejection_code="TEST2",
            rejection_reason="Second rejection.",
        )