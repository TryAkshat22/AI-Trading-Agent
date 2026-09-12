from datetime import date, datetime, timezone

import pytest

from database.account_storage import (
    AccountStorage,
)
from database.trading_storage import (
    TradingStorage,
)
from trading.orders import (
    Fill,
    Order,
    OrderSide,
    OrderStatus,
)
from trading.portfolio import money
from trading.portfolio_rebuilder import (
    PortfolioRebuildError,
    rebuild_portfolio,
)


def make_order(
    order_id,
    side,
    quantity,
):

    return Order(
        order_id=order_id,
        ticker="AAPL",
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
        execution_session=date(
            2026,
            9,
            8,
        ),
    )


def make_fill(
    order_id,
    side,
    quantity,
    price,
):

    return Fill(
        order_id=order_id,
        ticker="AAPL",
        side=side,
        quantity=quantity,
        reference_price=money(price),
        fill_price=money(price),
        gross_value=money(
            price * quantity
        ),
        fees=money(0),
        slippage_cost=money(0),
        execution_session=date(
            2026,
            9,
            8,
        ),
        status=OrderStatus.FILLED,
        realized_pnl=money(0),
    )


def test_empty_account_rebuilds_to_starting_cash(
    tmp_path,
):

    db = tmp_path / "test.db"

    accounts = AccountStorage(db)
    trades = TradingStorage(db)

    accounts.initialize()
    trades.initialize()

    accounts.create_account(
        starting_cash=10_000
    )

    portfolio = rebuild_portfolio(
        accounts,
        trades,
    )

    assert portfolio.cash == money(
        10_000
    )

    assert portfolio.positions == {}


def test_buy_fill_rebuilds_position(
    tmp_path,
):

    db = tmp_path / "test.db"

    accounts = AccountStorage(db)
    trades = TradingStorage(db)

    accounts.initialize()
    trades.initialize()

    accounts.create_account(
        starting_cash=10_000
    )

    order = make_order(
        "buy-1",
        OrderSide.BUY,
        10,
    )

    trades.save_order(order)

    trades.save_fill(
        make_fill(
            "buy-1",
            OrderSide.BUY,
            10,
            100,
        )
    )

    portfolio = rebuild_portfolio(
        accounts,
        trades,
    )

    assert portfolio.cash == money(
        9_000
    )

    position = portfolio.get_position(
        "AAPL"
    )

    assert position is not None
    assert position.quantity == 10
    assert position.average_cost == money(
        100
    )


def test_buy_and_sell_rebuild_correctly(
    tmp_path,
):

    db = tmp_path / "test.db"

    accounts = AccountStorage(db)
    trades = TradingStorage(db)

    accounts.initialize()
    trades.initialize()

    accounts.create_account(
        starting_cash=10_000
    )

    buy_order = make_order(
        "buy-1",
        OrderSide.BUY,
        10,
    )

    sell_order = make_order(
        "sell-1",
        OrderSide.SELL,
        5,
    )

    trades.save_order(
        buy_order
    )

    trades.save_fill(
        make_fill(
            "buy-1",
            OrderSide.BUY,
            10,
            100,
        )
    )

    trades.save_order(
        sell_order
    )

    trades.save_fill(
        make_fill(
            "sell-1",
            OrderSide.SELL,
            5,
            120,
        )
    )

    portfolio = rebuild_portfolio(
        accounts,
        trades,
    )

    assert portfolio.cash == money(
        9_600
    )

    assert portfolio.realized_pnl == money(
        100
    )

    position = portfolio.get_position(
        "AAPL"
    )

    assert position is not None
    assert position.quantity == 5


def test_missing_account_is_rejected(
    tmp_path,
):

    db = tmp_path / "test.db"

    accounts = AccountStorage(db)
    trades = TradingStorage(db)

    accounts.initialize()
    trades.initialize()

    with pytest.raises(
        PortfolioRebuildError
    ):
        rebuild_portfolio(
            accounts,
            trades,
        )