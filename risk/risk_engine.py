from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from trading.orders import OrderSide
from trading.portfolio import (
    Portfolio,
    money,
)


class RiskDecision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class RiskCode(str, Enum):
    APPROVED = "APPROVED"

    INVALID_TICKER = "INVALID_TICKER"
    INVALID_QUANTITY = "INVALID_QUANTITY"
    INVALID_PRICE = "INVALID_PRICE"

    MISSING_MARKET_PRICE = "MISSING_MARKET_PRICE"

    INSUFFICIENT_CASH = "INSUFFICIENT_CASH"
    INSUFFICIENT_SHARES = "INSUFFICIENT_SHARES"

    POSITION_LIMIT_EXCEEDED = "POSITION_LIMIT_EXCEEDED"
    INVESTED_CAPITAL_LIMIT_EXCEEDED = (
        "INVESTED_CAPITAL_LIMIT_EXCEEDED"
    )
    CASH_RESERVE_VIOLATION = "CASH_RESERVE_VIOLATION"
    MAX_OPEN_POSITIONS_EXCEEDED = (
        "MAX_OPEN_POSITIONS_EXCEEDED"
    )

    SHORTING_NOT_ALLOWED = "SHORTING_NOT_ALLOWED"


@dataclass(frozen=True)
class RiskConfig:
    """
    Model 1 portfolio-level risk limits.

    Percentages are expressed as decimals.

    Example:
        Decimal("0.10") = 10%
    """

    max_position_allocation: Decimal = Decimal("0.10")

    max_invested_allocation: Decimal = Decimal("0.70")

    minimum_cash_reserve: Decimal = Decimal("0.30")

    max_open_positions: int = 10

    allow_shorting: bool = False


@dataclass(frozen=True)
class RiskIssue:
    code: RiskCode
    message: str


@dataclass(frozen=True)
class RiskAssessment:
    decision: RiskDecision
    ticker: str
    side: OrderSide
    quantity: int
    reference_price: Decimal

    portfolio_equity: Decimal
    projected_cash: Decimal
    projected_position_value: Decimal
    projected_invested_value: Decimal

    issues: tuple[RiskIssue, ...]

    @property
    def approved(self) -> bool:
        return self.decision == RiskDecision.APPROVE


class RiskEngine:
    """
    Deterministic Model 1 risk gate.

    Responsibilities:
    - validate proposed trade inputs
    - enforce cash constraints
    - enforce position concentration
    - enforce total invested-capital limits
    - enforce minimum cash reserve
    - enforce maximum number of open positions
    - prevent unsupported shorting

    The risk engine does NOT:
    - generate trades
    - resize trades automatically
    - fetch prices
    - execute orders
    - alter portfolio state
    """

    def __init__(
        self,
        config: RiskConfig | None = None,
    ) -> None:

        self.config = (
            config
            if config is not None
            else RiskConfig()
        )

        self._validate_config()

    def assess(
        self,
        portfolio: Portfolio,
        ticker: str,
        side: OrderSide,
        quantity: int,
        reference_price,
        market_prices: dict,
        estimated_fees=0,
    ) -> RiskAssessment:

        ticker = ticker.strip().upper()

        issues: list[RiskIssue] = []

        price = money(reference_price)
        fees = money(estimated_fees)

        if not ticker:
            issues.append(
                RiskIssue(
                    code=RiskCode.INVALID_TICKER,
                    message="Ticker cannot be empty.",
                )
            )

        if not isinstance(quantity, int) or quantity <= 0:
            issues.append(
                RiskIssue(
                    code=RiskCode.INVALID_QUANTITY,
                    message=(
                        "Quantity must be a positive integer."
                    ),
                )
            )

        if price <= 0:
            issues.append(
                RiskIssue(
                    code=RiskCode.INVALID_PRICE,
                    message=(
                        "Reference price must be positive."
                    ),
                )
            )

        if fees < 0:
            issues.append(
                RiskIssue(
                    code=RiskCode.INVALID_PRICE,
                    message=(
                        "Estimated fees cannot be negative."
                    ),
                )
            )

        if issues:
            return self._rejected_early(
                ticker=ticker,
                side=side,
                quantity=quantity,
                price=price,
                issues=issues,
            )

        try:
            portfolio_equity = portfolio.total_equity(
                market_prices
            )

            current_market_value = portfolio.market_value(
                market_prices
            )

        except Exception as exc:
            return self._rejected_early(
                ticker=ticker,
                side=side,
                quantity=quantity,
                price=price,
                issues=[
                    RiskIssue(
                        code=RiskCode.MISSING_MARKET_PRICE,
                        message=(
                            "Portfolio valuation failed: "
                            f"{exc}"
                        ),
                    )
                ],
            )

        if portfolio_equity <= 0:
            return self._rejected_early(
                ticker=ticker,
                side=side,
                quantity=quantity,
                price=price,
                issues=[
                    RiskIssue(
                        code=RiskCode.INVALID_PRICE,
                        message=(
                            "Portfolio equity must be positive."
                        ),
                    )
                ],
            )

        current_position = portfolio.get_position(
            ticker
        )

        current_quantity = (
            current_position.quantity
            if current_position is not None
            else 0
        )

        current_position_price = money(
            market_prices.get(
                ticker,
                price,
            )
        )

        current_position_value = money(
            current_quantity
            * current_position_price
        )

        proposed_gross_value = money(
            quantity * price
        )

        projected_cash = portfolio.cash
        projected_position_value = (
            current_position_value
        )
        projected_invested_value = (
            current_market_value
        )

        if side == OrderSide.BUY:

            total_purchase_cost = money(
                proposed_gross_value + fees
            )

            projected_cash = money(
                portfolio.cash
                - total_purchase_cost
            )

            projected_position_value = money(
                current_position_value
                + proposed_gross_value
            )

            projected_invested_value = money(
                current_market_value
                + proposed_gross_value
            )

            if total_purchase_cost > portfolio.cash:
                issues.append(
                    RiskIssue(
                        code=RiskCode.INSUFFICIENT_CASH,
                        message=(
                            "Proposed purchase exceeds "
                            "available cash."
                        ),
                    )
                )

            projected_position_allocation = (
                Decimal(projected_position_value)
                / Decimal(portfolio_equity)
            )

            if (
                projected_position_allocation
                > self.config.max_position_allocation
            ):
                issues.append(
                    RiskIssue(
                        code=(
                            RiskCode
                            .POSITION_LIMIT_EXCEEDED
                        ),
                        message=(
                            "Projected position allocation "
                            "would exceed the configured "
                            "single-stock limit."
                        ),
                    )
                )

            projected_invested_allocation = (
                Decimal(projected_invested_value)
                / Decimal(portfolio_equity)
            )

            if (
                projected_invested_allocation
                > self.config.max_invested_allocation
            ):
                issues.append(
                    RiskIssue(
                        code=(
                            RiskCode
                            .INVESTED_CAPITAL_LIMIT_EXCEEDED
                        ),
                        message=(
                            "Projected invested capital "
                            "would exceed the configured "
                            "portfolio limit."
                        ),
                    )
                )

            projected_cash_allocation = (
                Decimal(projected_cash)
                / Decimal(portfolio_equity)
            )

            if (
                projected_cash_allocation
                < self.config.minimum_cash_reserve
            ):
                issues.append(
                    RiskIssue(
                        code=(
                            RiskCode
                            .CASH_RESERVE_VIOLATION
                        ),
                        message=(
                            "Projected cash would fall below "
                            "the minimum reserve."
                        ),
                    )
                )

            if (
                current_position is None
                and len(portfolio.positions)
                >= self.config.max_open_positions
            ):
                issues.append(
                    RiskIssue(
                        code=(
                            RiskCode
                            .MAX_OPEN_POSITIONS_EXCEEDED
                        ),
                        message=(
                            "Opening this position would "
                            "exceed the maximum number of "
                            "open positions."
                        ),
                    )
                )

        elif side == OrderSide.SELL:

            if current_position is None:
                issues.append(
                    RiskIssue(
                        code=RiskCode.INSUFFICIENT_SHARES,
                        message=(
                            f"No open position exists for "
                            f"{ticker}."
                        ),
                    )
                )

            elif quantity > current_position.quantity:

                if not self.config.allow_shorting:
                    issues.append(
                        RiskIssue(
                            code=(
                                RiskCode
                                .SHORTING_NOT_ALLOWED
                            ),
                            message=(
                                "Selling more shares than "
                                "currently owned would create "
                                "a short position."
                            ),
                        )
                    )

                else:
                    issues.append(
                        RiskIssue(
                            code=RiskCode.INSUFFICIENT_SHARES,
                            message=(
                                "Short-position risk logic "
                                "is not implemented in "
                                "Model 1."
                            ),
                        )
                    )

            else:

                projected_cash = money(
                    portfolio.cash
                    + proposed_gross_value
                    - fees
                )

                projected_position_value = money(
                    current_position_value
                    - proposed_gross_value
                )

                if projected_position_value < 0:
                    projected_position_value = money(0)

                projected_invested_value = money(
                    current_market_value
                    - proposed_gross_value
                )

                if projected_invested_value < 0:
                    projected_invested_value = money(0)

        else:

            issues.append(
                RiskIssue(
                    code=RiskCode.INVALID_QUANTITY,
                    message=(
                        f"Unsupported order side: {side}"
                    ),
                )
            )

        if issues:

            decision = RiskDecision.REJECT

        else:

            decision = RiskDecision.APPROVE

            issues.append(
                RiskIssue(
                    code=RiskCode.APPROVED,
                    message=(
                        "Trade passed all configured "
                        "Model 1 risk checks."
                    ),
                )
            )

        return RiskAssessment(
            decision=decision,
            ticker=ticker,
            side=side,
            quantity=quantity,
            reference_price=price,
            portfolio_equity=portfolio_equity,
            projected_cash=projected_cash,
            projected_position_value=(
                projected_position_value
            ),
            projected_invested_value=(
                projected_invested_value
            ),
            issues=tuple(issues),
        )

    def _validate_config(self) -> None:

        if not (
            Decimal("0")
            < self.config.max_position_allocation
            <= Decimal("1")
        ):
            raise ValueError(
                "max_position_allocation must be "
                "between 0 and 1."
            )

        if not (
            Decimal("0")
            < self.config.max_invested_allocation
            <= Decimal("1")
        ):
            raise ValueError(
                "max_invested_allocation must be "
                "between 0 and 1."
            )

        if not (
            Decimal("0")
            <= self.config.minimum_cash_reserve
            < Decimal("1")
        ):
            raise ValueError(
                "minimum_cash_reserve must be "
                "between 0 and 1."
            )

        if self.config.max_open_positions <= 0:
            raise ValueError(
                "max_open_positions must be positive."
            )

        if (
            self.config.minimum_cash_reserve
            + self.config.max_invested_allocation
            < Decimal("1")
        ):
            # This is allowed; it simply leaves additional
            # unused capital. No error is needed.
            pass

    @staticmethod
    def _rejected_early(
        ticker: str,
        side: OrderSide,
        quantity: int,
        price: Decimal,
        issues: list[RiskIssue],
    ) -> RiskAssessment:

        return RiskAssessment(
            decision=RiskDecision.REJECT,
            ticker=ticker,
            side=side,
            quantity=quantity,
            reference_price=price,
            portfolio_equity=money(0),
            projected_cash=money(0),
            projected_position_value=money(0),
            projected_invested_value=money(0),
            issues=tuple(issues),
        )