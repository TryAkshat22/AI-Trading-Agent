from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from trading.orders import (
    Fill,
    Order,
    OrderSide,
    OrderStatus,
)
from trading.portfolio import (
    Portfolio,
    PortfolioError,
    money,
)


class BrokerError(Exception):
    """Base exception for paper-broker failures."""


class DuplicateOrderError(BrokerError):
    """Raised when the same order ID is submitted twice."""


class InvalidExecutionError(BrokerError):
    """Raised when execution inputs are invalid."""


@dataclass(frozen=True)
class BrokerConfig:
    """
    Simple execution-cost model for Version 1.

    slippage_bps:
        Basis points added to BUY prices and subtracted
        from SELL prices.

    fee_per_trade:
        Flat simulated fee applied to each filled order.
    """

    slippage_bps: Decimal = Decimal("5")
    fee_per_trade: Decimal = Decimal("0.00")


class PaperBroker:
    """
    Deterministic paper broker for Model 1.

    Responsibilities:
    - execute explicit orders
    - prevent duplicate order execution
    - apply slippage
    - apply fees
    - enforce requested execution session
    - update Portfolio

    This broker does not fetch prices itself.
    The caller must provide the executable market price.
    """

    def __init__(
        self,
        portfolio: Portfolio,
        config: BrokerConfig | None = None,
    ) -> None:

        self.portfolio = portfolio

        self.config = (
            config
            if config is not None
            else BrokerConfig()
        )

        if self.config.slippage_bps < 0:
            raise ValueError(
                "Slippage cannot be negative."
            )

        if self.config.fee_per_trade < 0:
            raise ValueError(
                "Trade fee cannot be negative."
            )

        self._processed_order_ids: set[str] = set()

        self.fills: list[Fill] = []

    def execute(
        self,
        order: Order,
        market_price: float | int | str | Decimal,
        actual_session: date,
    ) -> Fill:

        self._validate_order(order)

        if order.order_id in self._processed_order_ids:
            raise DuplicateOrderError(
                f"Order {order.order_id} "
                f"has already been processed."
            )

        if actual_session != order.execution_session:
            raise InvalidExecutionError(
                f"Order {order.order_id} was scheduled "
                f"for {order.execution_session}, "
                f"but execution was attempted on "
                f"{actual_session}."
            )

        reference_price = money(
            market_price
        )

        if reference_price <= 0:
            raise InvalidExecutionError(
                "Market execution price must be positive."
            )

        fill_price = self._calculate_fill_price(
            side=order.side,
            reference_price=reference_price,
        )

        fees = money(
            self.config.fee_per_trade
        )

        slippage_cost = self._calculate_slippage_cost(
            side=order.side,
            reference_price=reference_price,
            fill_price=fill_price,
            quantity=order.quantity,
        )

        try:

            if order.side == OrderSide.BUY:

                trade = self.portfolio.buy(
                    ticker=order.ticker,
                    quantity=order.quantity,
                    price=fill_price,
                    fees=fees,
                )

            elif order.side == OrderSide.SELL:

                trade = self.portfolio.sell(
                    ticker=order.ticker,
                    quantity=order.quantity,
                    price=fill_price,
                    fees=fees,
                )

            else:
                raise InvalidExecutionError(
                    f"Unsupported order side: "
                    f"{order.side}"
                )

        except PortfolioError:
            # Failed portfolio validation must not count
            # as a successfully processed order.
            raise

        fill = Fill(
            order_id=order.order_id,
            ticker=order.ticker,
            side=order.side,
            quantity=order.quantity,
            reference_price=reference_price,
            fill_price=fill_price,
            gross_value=trade.gross_value,
            fees=fees,
            slippage_cost=slippage_cost,
            execution_session=actual_session,
            status=OrderStatus.FILLED,
            realized_pnl=trade.realized_pnl,
        )

        self._processed_order_ids.add(
            order.order_id
        )

        self.fills.append(
            fill
        )

        return fill

    def has_processed(
        self,
        order_id: str,
    ) -> bool:

        return (
            order_id
            in self._processed_order_ids
        )

    def _calculate_fill_price(
        self,
        side: OrderSide,
        reference_price: Decimal,
    ) -> Decimal:

        slippage_rate = (
            self.config.slippage_bps
            / Decimal("10000")
        )

        if side == OrderSide.BUY:

            fill_price = (
                reference_price
                * (
                    Decimal("1")
                    + slippage_rate
                )
            )

        elif side == OrderSide.SELL:

            fill_price = (
                reference_price
                * (
                    Decimal("1")
                    - slippage_rate
                )
            )

        else:
            raise InvalidExecutionError(
                f"Unsupported order side: {side}"
            )

        return money(
            fill_price
        )

    @staticmethod
    def _calculate_slippage_cost(
        side: OrderSide,
        reference_price: Decimal,
        fill_price: Decimal,
        quantity: int,
    ) -> Decimal:

        if side == OrderSide.BUY:

            difference = (
                fill_price
                - reference_price
            )

        else:

            difference = (
                reference_price
                - fill_price
            )

        return money(
            difference
            * quantity
        )

    @staticmethod
    def _validate_order(
        order: Order,
    ) -> None:

        if not order.order_id.strip():
            raise InvalidExecutionError(
                "Order ID cannot be empty."
            )

        if not order.ticker.strip():
            raise InvalidExecutionError(
                "Ticker cannot be empty."
            )

        if order.quantity <= 0:
            raise InvalidExecutionError(
                "Order quantity must be positive."
            )

        if (
            order.signal_timestamp_utc.tzinfo
            is None
        ):
            raise InvalidExecutionError(
                "Signal timestamp must be timezone-aware."
            )