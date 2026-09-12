from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from trading.orders import (
    Order,
    OrderSide,
    OrderStatus,
)
from trading.paper_broker import (
    BrokerConfig,
    DuplicateOrderError,
    InvalidExecutionError,
    PaperBroker,
)
from trading.portfolio import (
    InsufficientCashError,
    Portfolio,
    money,
)


def make_order(
    order_id="order-1",
    ticker="AAPL",
    side=OrderSide.BUY,
    quantity=10,
    execution_session=date(
        2026,
        9,
        8,
    ),
):

    return Order(
        order_id=order_id,
        ticker=ticker,
        side=side,
        quantity=quantity,
        signal_timestamp_utc=datetime(
            2026,
            9,
            4,
            21,
            0,
            tzinfo=timezone.utc,
        ),
        execution_session=execution_session,
    )


def test_buy_order_executes():

    portfolio = Portfolio(
        10_000
    )

    broker = PaperBroker(
        portfolio,
        BrokerConfig(
            slippage_bps=Decimal("0"),
        ),
    )

    order = make_order()

    fill = broker.execute(
        order=order,
        market_price=100,
        actual_session=date(
            2026,
            9,
            8,
        ),
    )

    assert fill.status == OrderStatus.FILLED
    assert fill.fill_price == money(100)

    assert portfolio.cash == money(
        9_000
    )

    assert broker.has_processed(
        "order-1"
    )


def test_buy_slippage_increases_fill_price():

    portfolio = Portfolio(
        10_000
    )

    broker = PaperBroker(
        portfolio,
        BrokerConfig(
            slippage_bps=Decimal("10"),
        ),
    )

    fill = broker.execute(
        order=make_order(),
        market_price=100,
        actual_session=date(
            2026,
            9,
            8,
        ),
    )

    assert fill.fill_price == money(
        100.10
    )

    assert fill.slippage_cost == money(
        1.00
    )


def test_sell_slippage_reduces_fill_price():

    portfolio = Portfolio(
        10_000
    )

    portfolio.buy(
        "AAPL",
        10,
        100,
    )

    broker = PaperBroker(
        portfolio,
        BrokerConfig(
            slippage_bps=Decimal("10"),
        ),
    )

    order = make_order(
        order_id="sell-1",
        side=OrderSide.SELL,
    )

    fill = broker.execute(
        order=order,
        market_price=110,
        actual_session=date(
            2026,
            9,
            8,
        ),
    )

    assert fill.fill_price == money(
        109.89
    )

    assert fill.slippage_cost == money(
        1.10
    )


def test_wrong_execution_session_rejected():

    portfolio = Portfolio(
        10_000
    )

    broker = PaperBroker(
        portfolio
    )

    with pytest.raises(
        InvalidExecutionError
    ):
        broker.execute(
            order=make_order(),
            market_price=100,
            actual_session=date(
                2026,
                9,
                9,
            ),
        )


def test_duplicate_order_is_rejected():

    portfolio = Portfolio(
        10_000
    )

    broker = PaperBroker(
        portfolio,
        BrokerConfig(
            slippage_bps=Decimal("0"),
        ),
    )

    order = make_order()

    broker.execute(
        order,
        market_price=100,
        actual_session=date(
            2026,
            9,
            8,
        ),
    )

    with pytest.raises(
        DuplicateOrderError
    ):
        broker.execute(
            order,
            market_price=100,
            actual_session=date(
                2026,
                9,
                8,
            ),
        )


def test_failed_order_does_not_become_processed():

    portfolio = Portfolio(
        500
    )

    broker = PaperBroker(
        portfolio,
        BrokerConfig(
            slippage_bps=Decimal("0"),
        ),
    )

    order = make_order(
        quantity=10
    )

    with pytest.raises(
        InsufficientCashError
    ):
        broker.execute(
            order,
            market_price=100,
            actual_session=date(
                2026,
                9,
                8,
            ),
        )

    assert not broker.has_processed(
        order.order_id
    )

    assert len(
        broker.fills
    ) == 0


def test_trade_fee_reduces_cash():

    portfolio = Portfolio(
        10_000
    )

    broker = PaperBroker(
        portfolio,
        BrokerConfig(
            slippage_bps=Decimal("0"),
            fee_per_trade=Decimal("2"),
        ),
    )

    broker.execute(
        make_order(),
        market_price=100,
        actual_session=date(
            2026,
            9,
            8,
        ),
    )

    assert portfolio.cash == money(
        8_998
    )


def test_invalid_market_price_rejected():

    portfolio = Portfolio(
        10_000
    )

    broker = PaperBroker(
        portfolio
    )

    with pytest.raises(
        InvalidExecutionError
    ):
        broker.execute(
            make_order(),
            market_price=0,
            actual_session=date(
                2026,
                9,
                8,
            ),
        )


def test_naive_signal_timestamp_rejected():

    portfolio = Portfolio(
        10_000
    )

    broker = PaperBroker(
        portfolio
    )

    order = Order(
        order_id="bad-time",
        ticker="AAPL",
        side=OrderSide.BUY,
        quantity=1,
        signal_timestamp_utc=datetime(
            2026,
            9,
            4,
            21,
            0,
        ),
        execution_session=date(
            2026,
            9,
            8,
        ),
    )

    with pytest.raises(
        InvalidExecutionError
    ):
        broker.execute(
            order,
            market_price=100,
            actual_session=date(
                2026,
                9,
                8,
            ),
        )