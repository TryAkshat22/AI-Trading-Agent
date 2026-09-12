from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_FLOOR

from trading.portfolio import Portfolio, money


class PositionSizingError(Exception):
    """Base exception for position-sizing failures."""


@dataclass(frozen=True)
class PositionSizerConfig:
    max_position_allocation: Decimal = Decimal("0.10")


@dataclass(frozen=True)
class PositionSizeResult:
    ticker: str
    reference_price: Decimal
    portfolio_equity: Decimal
    current_position_value: Decimal
    maximum_position_value: Decimal
    available_position_value: Decimal
    affordable_cash_value: Decimal
    quantity: int

    @property
    def can_trade(self) -> bool:
        return self.quantity > 0


class PositionSizer:
    """
    Simple allocation-based whole-share position sizer.

    It does not:
    - generate signals
    - execute trades
    - bypass the risk engine
    - use leverage
    - create fractional shares
    """

    def __init__(
        self,
        config: PositionSizerConfig | None = None,
    ) -> None:

        self.config = (
            config
            if config is not None
            else PositionSizerConfig()
        )

        self._validate_config()

    def size_buy(
        self,
        portfolio: Portfolio,
        ticker: str,
        reference_price,
        market_prices: dict,
    ) -> PositionSizeResult:

        ticker = ticker.strip().upper()

        if not ticker:
            raise PositionSizingError(
                "Ticker cannot be empty."
            )

        price = money(reference_price)

        if price <= 0:
            raise PositionSizingError(
                "Reference price must be positive."
            )

        try:
            portfolio_equity = portfolio.total_equity(
                market_prices
            )
        except Exception as exc:
            raise PositionSizingError(
                f"Portfolio valuation failed: {exc}"
            ) from exc

        if portfolio_equity <= 0:
            raise PositionSizingError(
                "Portfolio equity must be positive."
            )

        current_position = portfolio.get_position(
            ticker
        )

        if current_position is None:
            current_position_value = money(0)

        else:
            current_price = market_prices.get(
                ticker
            )

            if current_price is None:
                raise PositionSizingError(
                    f"Missing market price for existing "
                    f"position {ticker}."
                )

            current_position_value = money(
                current_position.quantity
                * money(current_price)
            )

        maximum_position_value = money(
            Decimal(portfolio_equity)
            * self.config.max_position_allocation
        )

        available_position_value = money(
            maximum_position_value
            - current_position_value
        )

        if available_position_value < 0:
            available_position_value = money(0)

        affordable_cash_value = min(
            money(portfolio.cash),
            available_position_value,
        )

        if affordable_cash_value <= 0:
            quantity = 0

        else:
            raw_quantity = (
                Decimal(affordable_cash_value)
                / Decimal(price)
            )

            quantity = int(
                raw_quantity.to_integral_value(
                    rounding=ROUND_FLOOR
                )
            )

        return PositionSizeResult(
            ticker=ticker,
            reference_price=price,
            portfolio_equity=portfolio_equity,
            current_position_value=(
                current_position_value
            ),
            maximum_position_value=(
                maximum_position_value
            ),
            available_position_value=(
                available_position_value
            ),
            affordable_cash_value=(
                affordable_cash_value
            ),
            quantity=quantity,
        )

    def _validate_config(self) -> None:

        allocation = (
            self.config.max_position_allocation
        )

        if not (
            Decimal("0")
            < allocation
            <= Decimal("1")
        ):
            raise ValueError(
                "max_position_allocation must be "
                "greater than 0 and at most 1."
            )


def size_buy_position(
    portfolio: Portfolio,
    ticker: str,
    reference_price,
    market_prices: dict,
    config: PositionSizerConfig | None = None,
) -> PositionSizeResult:

    sizer = PositionSizer(
        config=config
    )

    return sizer.size_buy(
        portfolio=portfolio,
        ticker=ticker,
        reference_price=reference_price,
        market_prices=market_prices,
    )