from decimal import Decimal

import pytest

from risk.position_sizer import (
    PositionSizer,
    PositionSizerConfig,
    PositionSizingError,
)
from trading.portfolio import Portfolio


def make_sizer():

    return PositionSizer(
        PositionSizerConfig(
            max_position_allocation=Decimal("0.10")
        )
    )


def test_empty_portfolio_sizes_to_ten_percent():

    portfolio = Portfolio(
        10_000
    )

    result = make_sizer().size_buy(
        portfolio=portfolio,
        ticker="AAPL",
        reference_price=100,
        market_prices={},
    )

    assert result.quantity == 10
    assert result.can_trade is True


def test_fractional_share_is_rounded_down():

    portfolio = Portfolio(
        10_000
    )

    result = make_sizer().size_buy(
        portfolio=portfolio,
        ticker="AAPL",
        reference_price=333,
        market_prices={},
    )

    assert result.quantity == 3


def test_expensive_stock_can_return_zero():

    portfolio = Portfolio(
        1_000
    )

    result = make_sizer().size_buy(
        portfolio=portfolio,
        ticker="AAPL",
        reference_price=500,
        market_prices={},
    )

    assert result.quantity == 0
    assert result.can_trade is False


def test_existing_position_reduces_available_size():

    portfolio = Portfolio(
        10_000
    )

    portfolio.buy(
        "AAPL",
        5,
        100,
    )

    result = make_sizer().size_buy(
        portfolio=portfolio,
        ticker="AAPL",
        reference_price=100,
        market_prices={
            "AAPL": 100,
        },
    )

    assert result.quantity == 5


def test_position_already_at_limit_returns_zero():

    portfolio = Portfolio(
        10_000
    )

    portfolio.buy(
        "AAPL",
        10,
        100,
    )

    result = make_sizer().size_buy(
        portfolio=portfolio,
        ticker="AAPL",
        reference_price=100,
        market_prices={
            "AAPL": 100,
        },
    )

    assert result.quantity == 0


def test_cash_can_be_more_restrictive_than_allocation():

    portfolio = Portfolio(
        10_000
    )

    portfolio.buy(
        "MSFT",
        95,
        100,
    )

    sizer = PositionSizer(
        PositionSizerConfig(
            max_position_allocation=Decimal("1")
        )
    )

    result = sizer.size_buy(
        portfolio=portfolio,
        ticker="AAPL",
        reference_price=100,
        market_prices={
            "MSFT": 100,
        },
    )

    assert result.quantity == 5


def test_missing_price_for_existing_position_fails():

    portfolio = Portfolio(
        10_000
    )

    portfolio.buy(
        "MSFT",
        5,
        100,
    )

    with pytest.raises(
        PositionSizingError
    ):
        make_sizer().size_buy(
            portfolio=portfolio,
            ticker="AAPL",
            reference_price=100,
            market_prices={},
        )


def test_missing_price_for_same_ticker_fails():

    portfolio = Portfolio(
        10_000
    )

    portfolio.buy(
        "AAPL",
        5,
        100,
    )

    with pytest.raises(
        PositionSizingError
    ):
        make_sizer().size_buy(
            portfolio=portfolio,
            ticker="AAPL",
            reference_price=100,
            market_prices={},
        )


def test_invalid_reference_price_fails():

    portfolio = Portfolio(
        10_000
    )

    with pytest.raises(
        PositionSizingError
    ):
        make_sizer().size_buy(
            portfolio=portfolio,
            ticker="AAPL",
            reference_price=0,
            market_prices={},
        )


def test_empty_ticker_fails():

    portfolio = Portfolio(
        10_000
    )

    with pytest.raises(
        PositionSizingError
    ):
        make_sizer().size_buy(
            portfolio=portfolio,
            ticker="",
            reference_price=100,
            market_prices={},
        )


def test_invalid_config_fails():

    with pytest.raises(
        ValueError
    ):
        PositionSizer(
            PositionSizerConfig(
                max_position_allocation=Decimal(
                    "1.5"
                )
            )
        )