from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP


MONEY_PLACES = Decimal("0.01")


def money(value: float | int | str | Decimal) -> Decimal:
    """
    Convert a numeric value to a two-decimal Decimal.

    We use Decimal instead of float for portfolio accounting
    to reduce rounding errors in cash and P/L calculations.
    """
    return Decimal(str(value)).quantize(
        MONEY_PLACES,
        rounding=ROUND_HALF_UP,
    )


class PortfolioError(Exception):
    """Base exception for portfolio/accounting failures."""


class InsufficientCashError(PortfolioError):
    """Raised when a purchase exceeds available cash."""


class InsufficientSharesError(PortfolioError):
    """Raised when selling more shares than are owned."""


class InvalidTradeError(PortfolioError):
    """Raised for invalid quantities or prices."""


@dataclass
class Position:
    ticker: str
    quantity: int
    average_cost: Decimal

    @property
    def cost_basis(self) -> Decimal:
        return money(
            self.average_cost * self.quantity
        )


@dataclass(frozen=True)
class TradeResult:
    ticker: str
    action: str
    quantity: int
    price: Decimal
    gross_value: Decimal
    fees: Decimal
    realized_pnl: Decimal
    cash_after: Decimal


class Portfolio:
    """
    In-memory long-only portfolio for Model 1.

    Responsibilities:
    - cash accounting
    - position accounting
    - average-cost tracking
    - realized P/L
    - unrealized P/L
    - total equity

    Shorting is deliberately unsupported in Version 1.
    """

    def __init__(
        self,
        starting_cash: float | int | str | Decimal,
    ) -> None:

        starting_cash = money(starting_cash)

        if starting_cash <= 0:
            raise ValueError(
                "Starting cash must be positive."
            )

        self.starting_cash = starting_cash
        self.cash = starting_cash

        self.positions: dict[str, Position] = {}

        self.realized_pnl = money(0)

    def buy(
        self,
        ticker: str,
        quantity: int,
        price: float | int | str | Decimal,
        fees: float | int | str | Decimal = 0,
    ) -> TradeResult:

        ticker = self._normalize_ticker(ticker)
        self._validate_quantity(quantity)

        price = money(price)
        fees = money(fees)

        self._validate_price(price)
        self._validate_fees(fees)

        gross_value = money(
            price * quantity
        )

        total_cost = money(
            gross_value + fees
        )

        if total_cost > self.cash:
            raise InsufficientCashError(
                f"Insufficient cash to buy "
                f"{quantity} share(s) of {ticker}. "
                f"Required: ${total_cost}, "
                f"available: ${self.cash}."
            )

        existing = self.positions.get(
            ticker
        )

        if existing is None:

            average_cost = money(
                total_cost / quantity
            )

            self.positions[ticker] = Position(
                ticker=ticker,
                quantity=quantity,
                average_cost=average_cost,
            )

        else:

            existing_cost = (
                existing.average_cost
                * existing.quantity
            )

            new_total_cost = (
                existing_cost
                + total_cost
            )

            new_quantity = (
                existing.quantity
                + quantity
            )

            new_average_cost = money(
                new_total_cost
                / new_quantity
            )

            existing.quantity = (
                new_quantity
            )

            existing.average_cost = (
                new_average_cost
            )

        self.cash = money(
            self.cash - total_cost
        )

        return TradeResult(
            ticker=ticker,
            action="BUY",
            quantity=quantity,
            price=price,
            gross_value=gross_value,
            fees=fees,
            realized_pnl=money(0),
            cash_after=self.cash,
        )

    def sell(
        self,
        ticker: str,
        quantity: int,
        price: float | int | str | Decimal,
        fees: float | int | str | Decimal = 0,
    ) -> TradeResult:

        ticker = self._normalize_ticker(ticker)
        self._validate_quantity(quantity)

        price = money(price)
        fees = money(fees)

        self._validate_price(price)
        self._validate_fees(fees)

        position = self.positions.get(
            ticker
        )

        if position is None:
            raise InsufficientSharesError(
                f"No open position exists for {ticker}."
            )

        if quantity > position.quantity:
            raise InsufficientSharesError(
                f"Cannot sell {quantity} share(s) "
                f"of {ticker}; only "
                f"{position.quantity} owned."
            )

        gross_value = money(
            price * quantity
        )

        net_proceeds = money(
            gross_value - fees
        )

        cost_basis_sold = money(
            position.average_cost
            * quantity
        )

        realized_pnl = money(
            net_proceeds
            - cost_basis_sold
        )

        self.cash = money(
            self.cash
            + net_proceeds
        )

        self.realized_pnl = money(
            self.realized_pnl
            + realized_pnl
        )

        position.quantity -= quantity

        if position.quantity == 0:
            del self.positions[ticker]

        return TradeResult(
            ticker=ticker,
            action="SELL",
            quantity=quantity,
            price=price,
            gross_value=gross_value,
            fees=fees,
            realized_pnl=realized_pnl,
            cash_after=self.cash,
        )

    def market_value(
        self,
        prices: dict[str, float | int | str | Decimal],
    ) -> Decimal:

        total = money(0)

        for ticker, position in self.positions.items():

            if ticker not in prices:
                raise PortfolioError(
                    f"Missing market price for {ticker}."
                )

            current_price = money(
                prices[ticker]
            )

            self._validate_price(
                current_price
            )

            total = money(
                total
                + current_price
                * position.quantity
            )

        return total

    def unrealized_pnl(
        self,
        prices: dict[str, float | int | str | Decimal],
    ) -> Decimal:

        pnl = money(0)

        for ticker, position in self.positions.items():

            if ticker not in prices:
                raise PortfolioError(
                    f"Missing market price for {ticker}."
                )

            current_price = money(
                prices[ticker]
            )

            self._validate_price(
                current_price
            )

            position_value = (
                current_price
                * position.quantity
            )

            position_cost = (
                position.average_cost
                * position.quantity
            )

            pnl = money(
                pnl
                + position_value
                - position_cost
            )

        return pnl

    def total_equity(
        self,
        prices: dict[str, float | int | str | Decimal],
    ) -> Decimal:

        return money(
            self.cash
            + self.market_value(prices)
        )

    def get_position(
        self,
        ticker: str,
    ) -> Position | None:

        ticker = self._normalize_ticker(
            ticker
        )

        return self.positions.get(
            ticker
        )

    @staticmethod
    def _normalize_ticker(
        ticker: str,
    ) -> str:

        ticker = ticker.strip().upper()

        if not ticker:
            raise InvalidTradeError(
                "Ticker cannot be empty."
            )

        return ticker

    @staticmethod
    def _validate_quantity(
        quantity: int,
    ) -> None:

        if not isinstance(
            quantity,
            int,
        ):
            raise InvalidTradeError(
                "Quantity must be an integer."
            )

        if quantity <= 0:
            raise InvalidTradeError(
                "Quantity must be greater than zero."
            )

    @staticmethod
    def _validate_price(
        price: Decimal,
    ) -> None:

        if price <= 0:
            raise InvalidTradeError(
                "Trade price must be positive."
            )

    @staticmethod
    def _validate_fees(
        fees: Decimal,
    ) -> None:

        if fees < 0:
            raise InvalidTradeError(
                "Fees cannot be negative."
            )