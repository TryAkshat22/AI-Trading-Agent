from __future__ import annotations

from decimal import Decimal

import pytest

from evaluation.portfolio_report import (
    PortfolioPriceError,
    PortfolioReportService,
)
from trading.portfolio import (
    Portfolio,
)


class FakeRebuilder:

    def __init__(
        self,
        portfolio,
    ) -> None:

        self.portfolio = (
            portfolio
        )

        self.account_ids = []

    def rebuild(
        self,
        account_id="model1-paper",
    ):

        self.account_ids.append(
            account_id
        )

        return self.portfolio


class FakeTradingStorage:

    def __init__(
        self,
        fill_count=0,
    ) -> None:

        self.fill_count = (
            fill_count
        )

    def count_fills(
        self,
    ):

        return self.fill_count


def build_service(
    portfolio,
    prices,
    fill_count=0,
):

    def price_fetcher(
        ticker,
    ):

        return prices[
            ticker
        ]

    return PortfolioReportService(
        portfolio_rebuilder=(
            FakeRebuilder(
                portfolio
            )
        ),
        trading_storage=(
            FakeTradingStorage(
                fill_count
            )
        ),
        market_price_fetcher=(
            price_fetcher
        ),
    )


def test_empty_portfolio():

    portfolio = (
        Portfolio(
            10_000
        )
    )

    service = build_service(
        portfolio=portfolio,
        prices={},
    )

    report = (
        service.build()
    )

    assert (
        report.starting_cash
        == Decimal(
            "10000.00"
        )
    )

    assert (
        report.cash
        == Decimal(
            "10000.00"
        )
    )

    assert (
        report.market_value
        == Decimal(
            "0.00"
        )
    )

    assert (
        report.total_equity
        == Decimal(
            "10000.00"
        )
    )

    assert (
        report.total_return_pct
        == Decimal(
            "0"
        )
    )

    assert (
        report.exposure_pct
        == Decimal(
            "0"
        )
    )

    assert (
        report.open_positions
        == 0
    )


def test_single_open_position():

    portfolio = (
        Portfolio(
            10_000
        )
    )

    portfolio.buy(
        ticker="AAPL",
        quantity=10,
        price=100,
    )

    service = build_service(
        portfolio=portfolio,
        prices={
            "AAPL": 110,
        },
        fill_count=1,
    )

    report = (
        service.build()
    )

    assert (
        report.cash
        == Decimal(
            "9000.00"
        )
    )

    assert (
        report.market_value
        == Decimal(
            "1100.00"
        )
    )

    assert (
        report.total_equity
        == Decimal(
            "10100.00"
        )
    )

    assert (
        report.unrealized_pnl
        == Decimal(
            "100.00"
        )
    )

    assert (
        report.total_pnl
        == Decimal(
            "100.00"
        )
    )

    assert (
        report.trade_count
        == 1
    )


def test_position_report_values():

    portfolio = (
        Portfolio(
            10_000
        )
    )

    portfolio.buy(
        ticker="AAPL",
        quantity=10,
        price=100,
    )

    report = (
        build_service(
            portfolio,
            {
                "AAPL": 110,
            },
        )
        .build()
    )

    position = (
        report.positions[
            0
        ]
    )

    assert (
        position.ticker
        == "AAPL"
    )

    assert (
        position.quantity
        == 10
    )

    assert (
        position.average_cost
        == Decimal(
            "100.00"
        )
    )

    assert (
        position.cost_basis
        == Decimal(
            "1000.00"
        )
    )

    assert (
        position.market_value
        == Decimal(
            "1100"
        )
    )

    assert (
        position.unrealized_pnl
        == Decimal(
            "100.00"
        )
    )

    assert (
        position.unrealized_return_pct
        == Decimal(
            "10.0"
        )
    )


def test_multiple_positions():

    portfolio = (
        Portfolio(
            10_000
        )
    )

    portfolio.buy(
        "AAPL",
        10,
        100,
    )

    portfolio.buy(
        "MSFT",
        5,
        200,
    )

    report = (
        build_service(
            portfolio,
            {
                "AAPL": 110,
                "MSFT": 190,
            },
        )
        .build()
    )

    assert (
        report.market_value
        == Decimal(
            "2050.00"
        )
    )

    assert (
        report.unrealized_pnl
        == Decimal(
            "50.00"
        )
    )

    assert (
        report.open_positions
        == 2
    )


def test_realized_pnl_is_included():

    portfolio = (
        Portfolio(
            10_000
        )
    )

    portfolio.buy(
        "AAPL",
        10,
        100,
    )

    portfolio.sell(
        "AAPL",
        5,
        120,
    )

    report = (
        build_service(
            portfolio,
            {
                "AAPL": 110,
            },
            fill_count=2,
        )
        .build()
    )

    assert (
        report.realized_pnl
        == Decimal(
            "100.00"
        )
    )

    assert (
        report.unrealized_pnl
        == Decimal(
            "50.00"
        )
    )

    assert (
        report.total_pnl
        == Decimal(
            "150.00"
        )
    )


def test_total_return_uses_equity():

    portfolio = (
        Portfolio(
            10_000
        )
    )

    portfolio.buy(
        "AAPL",
        10,
        100,
    )

    report = (
        build_service(
            portfolio,
            {
                "AAPL": 110,
            },
        )
        .build()
    )

    assert (
        report.total_return_pct
        == Decimal(
            "1.00"
        )
    )


def test_exposure_is_market_value_over_equity():

    portfolio = (
        Portfolio(
            10_000
        )
    )

    portfolio.buy(
        "AAPL",
        10,
        100,
    )

    report = (
        build_service(
            portfolio,
            {
                "AAPL": 100,
            },
        )
        .build()
    )

    assert (
        report.exposure_pct
        == Decimal(
            "10.0"
        )
    )


def test_invalid_price_rejected():

    portfolio = (
        Portfolio(
            10_000
        )
    )

    portfolio.buy(
        "AAPL",
        10,
        100,
    )

    service = build_service(
        portfolio,
        {
            "AAPL": 0,
        },
    )

    with pytest.raises(
        PortfolioPriceError
    ):

        service.build()


def test_missing_price_rejected():

    portfolio = (
        Portfolio(
            10_000
        )
    )

    portfolio.buy(
        "AAPL",
        10,
        100,
    )

    service = build_service(
        portfolio,
        {},
    )

    with pytest.raises(
        PortfolioPriceError
    ):

        service.build()


def test_positions_sorted_by_ticker():

    portfolio = (
        Portfolio(
            10_000
        )
    )

    portfolio.buy(
        "MSFT",
        1,
        100,
    )

    portfolio.buy(
        "AAPL",
        1,
        100,
    )

    report = (
        build_service(
            portfolio,
            {
                "MSFT": 100,
                "AAPL": 100,
            },
        )
        .build()
    )

    assert [
        position.ticker
        for position in report.positions
    ] == [
        "AAPL",
        "MSFT",
    ]