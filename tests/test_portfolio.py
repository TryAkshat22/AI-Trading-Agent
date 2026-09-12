import pytest

from trading.portfolio import (
    InsufficientCashError,
    InsufficientSharesError,
    InvalidTradeError,
    Portfolio,
    PortfolioError,
    money,
)


def test_portfolio_initializes():

    portfolio = Portfolio(
        starting_cash=10_000
    )

    assert portfolio.cash == money(10_000)
    assert portfolio.realized_pnl == money(0)
    assert portfolio.positions == {}


def test_buy_reduces_cash():

    portfolio = Portfolio(10_000)

    result = portfolio.buy(
        ticker="AAPL",
        quantity=10,
        price=100,
    )

    assert result.action == "BUY"

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


def test_buy_with_fees_updates_cost_basis():

    portfolio = Portfolio(10_000)

    portfolio.buy(
        ticker="AAPL",
        quantity=10,
        price=100,
        fees=10,
    )

    position = portfolio.get_position(
        "AAPL"
    )

    assert position.average_cost == money(
        101
    )

    assert portfolio.cash == money(
        8_990
    )


def test_second_buy_updates_average_cost():

    portfolio = Portfolio(10_000)

    portfolio.buy(
        "AAPL",
        10,
        100,
    )

    portfolio.buy(
        "AAPL",
        10,
        120,
    )

    position = portfolio.get_position(
        "AAPL"
    )

    assert position.quantity == 20

    assert position.average_cost == money(
        110
    )


def test_sell_creates_realized_profit():

    portfolio = Portfolio(10_000)

    portfolio.buy(
        "AAPL",
        10,
        100,
    )

    result = portfolio.sell(
        "AAPL",
        5,
        120,
    )

    assert result.realized_pnl == money(
        100
    )

    assert portfolio.realized_pnl == money(
        100
    )

    assert portfolio.cash == money(
        9_600
    )

    position = portfolio.get_position(
        "AAPL"
    )

    assert position.quantity == 5


def test_full_sell_removes_position():

    portfolio = Portfolio(10_000)

    portfolio.buy(
        "AAPL",
        10,
        100,
    )

    portfolio.sell(
        "AAPL",
        10,
        110,
    )

    assert (
        portfolio.get_position("AAPL")
        is None
    )

    assert portfolio.cash == money(
        10_100
    )


def test_sell_with_fees_reduces_profit():

    portfolio = Portfolio(10_000)

    portfolio.buy(
        "AAPL",
        10,
        100,
    )

    result = portfolio.sell(
        "AAPL",
        10,
        110,
        fees=10,
    )

    assert result.realized_pnl == money(
        90
    )


def test_insufficient_cash_is_rejected():

    portfolio = Portfolio(1_000)

    with pytest.raises(
        InsufficientCashError
    ):
        portfolio.buy(
            "AAPL",
            20,
            100,
        )

    assert portfolio.cash == money(
        1_000
    )

    assert portfolio.positions == {}


def test_cannot_sell_more_than_owned():

    portfolio = Portfolio(10_000)

    portfolio.buy(
        "AAPL",
        5,
        100,
    )

    with pytest.raises(
        InsufficientSharesError
    ):
        portfolio.sell(
            "AAPL",
            6,
            110,
        )


def test_cannot_sell_without_position():

    portfolio = Portfolio(10_000)

    with pytest.raises(
        InsufficientSharesError
    ):
        portfolio.sell(
            "AAPL",
            1,
            100,
        )


def test_negative_quantity_is_rejected():

    portfolio = Portfolio(10_000)

    with pytest.raises(
        InvalidTradeError
    ):
        portfolio.buy(
            "AAPL",
            -1,
            100,
        )


def test_zero_price_is_rejected():

    portfolio = Portfolio(10_000)

    with pytest.raises(
        InvalidTradeError
    ):
        portfolio.buy(
            "AAPL",
            1,
            0,
        )


def test_market_value():

    portfolio = Portfolio(10_000)

    portfolio.buy(
        "AAPL",
        10,
        100,
    )

    value = portfolio.market_value(
        {
            "AAPL": 110,
        }
    )

    assert value == money(
        1_100
    )


def test_unrealized_profit():

    portfolio = Portfolio(10_000)

    portfolio.buy(
        "AAPL",
        10,
        100,
    )

    pnl = portfolio.unrealized_pnl(
        {
            "AAPL": 110,
        }
    )

    assert pnl == money(
        100
    )


def test_total_equity():

    portfolio = Portfolio(10_000)

    portfolio.buy(
        "AAPL",
        10,
        100,
    )

    equity = portfolio.total_equity(
        {
            "AAPL": 110,
        }
    )

    assert equity == money(
        10_100
    )


def test_missing_market_price_is_rejected():

    portfolio = Portfolio(10_000)

    portfolio.buy(
        "AAPL",
        10,
        100,
    )

    with pytest.raises(
        PortfolioError
    ):
        portfolio.total_equity({})