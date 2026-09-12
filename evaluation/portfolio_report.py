from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Callable

from trading.portfolio_rebuilder import (
    PortfolioRebuilder,
)


class PortfolioReportError(Exception):
    """
    Base error for portfolio reporting.
    """


class PortfolioPriceError(
    PortfolioReportError
):
    """
    Raised when a required market price is
    missing or invalid.
    """


def _decimal(
    value,
) -> Decimal:

    try:

        result = Decimal(
            str(
                value
            )
        )

    except (
        InvalidOperation,
        TypeError,
        ValueError,
    ) as exc:

        raise PortfolioPriceError(
            f"Invalid numeric value: {value!r}"
        ) from exc

    return result


@dataclass(frozen=True)
class PositionReport:

    ticker: str
    quantity: int

    average_cost: Decimal
    current_price: Decimal

    cost_basis: Decimal
    market_value: Decimal

    unrealized_pnl: Decimal
    unrealized_return_pct: Decimal


@dataclass(frozen=True)
class PortfolioReport:

    account_id: str

    starting_cash: Decimal
    cash: Decimal

    market_value: Decimal
    total_equity: Decimal

    realized_pnl: Decimal
    unrealized_pnl: Decimal
    total_pnl: Decimal

    total_return_pct: Decimal
    exposure_pct: Decimal

    open_positions: int
    trade_count: int

    positions: tuple[
        PositionReport,
        ...,
    ]


class PortfolioReportService:
    """
    Read-only portfolio performance report.

    The service:
        - rebuilds the persisted portfolio
        - retrieves prices only for open positions
        - calculates current portfolio metrics
        - does not create or modify trading state
    """

    def __init__(
        self,
        portfolio_rebuilder: PortfolioRebuilder,
        trading_storage,
        market_price_fetcher: Callable[
            [str],
            Decimal | float | int | str,
        ],
    ) -> None:

        self.portfolio_rebuilder = (
            portfolio_rebuilder
        )

        self.trading_storage = (
            trading_storage
        )

        self.market_price_fetcher = (
            market_price_fetcher
        )

    def _get_price(
        self,
        ticker: str,
    ) -> Decimal:

        try:

            raw_price = (
                self.market_price_fetcher(
                    ticker
                )
            )

        except Exception as exc:

            raise PortfolioPriceError(
                f"Could not retrieve a market "
                f"price for {ticker}."
            ) from exc

        price = _decimal(
            raw_price
        )

        if price <= 0:

            raise PortfolioPriceError(
                f"Market price for {ticker} "
                "must be positive."
            )

        return price

    def build(
        self,
        account_id: str = "model1-paper",
    ) -> PortfolioReport:

        portfolio = (
            self.portfolio_rebuilder
            .rebuild(
                account_id=account_id
            )
        )

        prices: dict[
            str,
            Decimal,
        ] = {}

        for ticker in sorted(
            portfolio.positions
        ):

            prices[
                ticker
            ] = self._get_price(
                ticker
            )

        market_value = (
            portfolio.market_value(
                prices
            )
        )

        total_equity = (
            portfolio.total_equity(
                prices
            )
        )

        unrealized_pnl = (
            portfolio.unrealized_pnl(
                prices
            )
        )

        realized_pnl = (
            portfolio.realized_pnl
        )

        total_pnl = (
            realized_pnl
            + unrealized_pnl
        )

        starting_cash = (
            portfolio.starting_cash
        )

        if starting_cash > 0:

            total_return_pct = (
                (
                    total_equity
                    - starting_cash
                )
                / starting_cash
                * Decimal(
                    "100"
                )
            )

        else:

            total_return_pct = (
                Decimal(
                    "0"
                )
            )

        if total_equity > 0:

            exposure_pct = (
                market_value
                / total_equity
                * Decimal(
                    "100"
                )
            )

        else:

            exposure_pct = (
                Decimal(
                    "0"
                )
            )

        position_reports: list[
            PositionReport
        ] = []

        for ticker in sorted(
            portfolio.positions
        ):

            position = (
                portfolio.positions[
                    ticker
                ]
            )

            current_price = (
                prices[
                    ticker
                ]
            )

            cost_basis = (
                position.cost_basis
            )

            position_market_value = (
                current_price
                * position.quantity
            )

            position_unrealized_pnl = (
                position_market_value
                - cost_basis
            )

            if cost_basis > 0:

                position_return_pct = (
                    position_unrealized_pnl
                    / cost_basis
                    * Decimal(
                        "100"
                    )
                )

            else:

                position_return_pct = (
                    Decimal(
                        "0"
                    )
                )

            position_reports.append(
                PositionReport(
                    ticker=(
                        position.ticker
                    ),
                    quantity=(
                        position.quantity
                    ),
                    average_cost=(
                        position.average_cost
                    ),
                    current_price=(
                        current_price
                    ),
                    cost_basis=(
                        cost_basis
                    ),
                    market_value=(
                        position_market_value
                    ),
                    unrealized_pnl=(
                        position_unrealized_pnl
                    ),
                    unrealized_return_pct=(
                        position_return_pct
                    ),
                )
            )

        return PortfolioReport(
            account_id=(
                account_id
            ),
            starting_cash=(
                starting_cash
            ),
            cash=(
                portfolio.cash
            ),
            market_value=(
                market_value
            ),
            total_equity=(
                total_equity
            ),
            realized_pnl=(
                realized_pnl
            ),
            unrealized_pnl=(
                unrealized_pnl
            ),
            total_pnl=(
                total_pnl
            ),
            total_return_pct=(
                total_return_pct
            ),
            exposure_pct=(
                exposure_pct
            ),
            open_positions=(
                len(
                    portfolio.positions
                )
            ),
            trade_count=(
                self.trading_storage
                .count_fills()
            ),
            positions=tuple(
                position_reports
            ),
        )


def print_portfolio_report(
    report: PortfolioReport,
) -> None:

    print()
    print(
        "Portfolio Performance"
    )

    print(
        "====================="
    )

    print(
        f"Account: "
        f"{report.account_id}"
    )

    print()

    print(
        f"Starting cash:       "
        f"${report.starting_cash:,.2f}"
    )

    print(
        f"Current cash:        "
        f"${report.cash:,.2f}"
    )

    print(
        f"Market value:        "
        f"${report.market_value:,.2f}"
    )

    print(
        f"Total equity:        "
        f"${report.total_equity:,.2f}"
    )

    print()

    print(
        f"Realized P&L:        "
        f"${report.realized_pnl:,.2f}"
    )

    print(
        f"Unrealized P&L:      "
        f"${report.unrealized_pnl:,.2f}"
    )

    print(
        f"Total P&L:           "
        f"${report.total_pnl:,.2f}"
    )

    print(
        f"Total return:        "
        f"{report.total_return_pct:.2f}%"
    )

    print(
        f"Exposure:            "
        f"{report.exposure_pct:.2f}%"
    )

    print()

    print(
        f"Open positions:      "
        f"{report.open_positions}"
    )

    print(
        f"Recorded fills:      "
        f"{report.trade_count}"
    )

    if not report.positions:

        print()
        print(
            "No open positions."
        )

        return

    print()
    print(
        "Positions"
    )

    print(
        "---------"
    )

    for position in report.positions:

        print()

        print(
            f"{position.ticker}"
        )

        print(
            f"  Quantity:          "
            f"{position.quantity}"
        )

        print(
            f"  Average cost:      "
            f"${position.average_cost:,.2f}"
        )

        print(
            f"  Current price:     "
            f"${position.current_price:,.2f}"
        )

        print(
            f"  Cost basis:        "
            f"${position.cost_basis:,.2f}"
        )

        print(
            f"  Market value:      "
            f"${position.market_value:,.2f}"
        )

        print(
            f"  Unrealized P&L:    "
            f"${position.unrealized_pnl:,.2f}"
        )

        print(
            f"  Position return:   "
            f"{position.unrealized_return_pct:.2f}%"
        )