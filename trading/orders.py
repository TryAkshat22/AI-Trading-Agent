from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum

from trading.portfolio import money


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    FILLED = "FILLED"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class Order:
    order_id: str
    ticker: str
    side: OrderSide
    quantity: int
    signal_timestamp_utc: datetime
    execution_session: date


@dataclass(frozen=True)
class Fill:
    order_id: str
    ticker: str
    side: OrderSide
    quantity: int

    reference_price: Decimal
    fill_price: Decimal

    gross_value: Decimal
    fees: Decimal
    slippage_cost: Decimal

    execution_session: date
    status: OrderStatus

    realized_pnl: Decimal = money(0)