
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Callable

from model2_execution_readiness import check_execution_window
from risk.risk_engine import RiskAssessment, RiskEngine
from trading.flexible_execution_observation import (
    FlexibleExecutionObservation,
)
from trading.orders import Order, OrderSide
from trading.paper_broker import BrokerConfig
from trading.portfolio import Portfolio, money


class Model2ExecutionRiskError(RuntimeError):
    """Execution-risk inputs are invalid or no longer fresh."""


@dataclass(frozen=True)
class Model2ExecutionRiskResult:
    order_id: str
    reference_price: Decimal
    projected_fill_price: Decimal
    assessment: RiskAssessment
    checked_at_utc: datetime


def assess_model2_execution_risk(
    *,
    order: Order,
    observation: FlexibleExecutionObservation,
    portfolio: Portfolio,
    market_prices: dict,
    clock: Callable[[], datetime],
    risk_engine: RiskEngine | None = None,
    broker_config: BrokerConfig | None = None,
) -> Model2ExecutionRiskResult:
    """
    Calculation only. Does not execute or persist trades.

    The eventual executor must call this while holding
    Model 2's database write lock, after rebuilding
    the portfolio from committed fills.
    """
    now = clock()

    if (
        not isinstance(now, datetime)
        or now.tzinfo is None
        or now.utcoffset() is None
    ):
        raise Model2ExecutionRiskError(
            "Clock must return a timezone-aware datetime."
        )

    now = now.astimezone(timezone.utc)
    check_execution_window(order.execution_session, now)

    if (
        observation.ticker != order.ticker
        or observation.execution_session != order.execution_session
        or observation.price_field != "Close"
        or observation.model != "flexible-observed-close-v1"
    ):
        raise Model2ExecutionRiskError(
            "Observation does not match the order "
            "or the expected execution-price model."
        )

    timestamps = (
        observation.bar_start_utc,
        observation.bar_end_utc,
        observation.retrieved_at_utc,
        observation.execution_checked_at_utc,
    )

    if any(
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
        for value in timestamps
    ):
        raise Model2ExecutionRiskError(
            "Observation timestamps must be timezone-aware."
        )

    bar_start, bar_end, retrieved, checked = (
        value.astimezone(timezone.utc)
        for value in timestamps
    )

    if (
        bar_end - bar_start != timedelta(minutes=1)
        or bar_end > retrieved
        or retrieved > checked
        or checked > now
        or now - bar_end > timedelta(minutes=5)
    ):
        raise Model2ExecutionRiskError(
            "Observation is incomplete, stale, "
            "or was not available at the check time."
        )

    try:
        raw_price = float(observation.reference_price)
    except (TypeError, ValueError) as exc:
        raise Model2ExecutionRiskError(
            "Reference price must be numeric."
        ) from exc

    if not math.isfinite(raw_price) or raw_price <= 0:
        raise Model2ExecutionRiskError(
            "Reference price must be finite and positive."
        )

    config = (
        broker_config
        if broker_config is not None
        else BrokerConfig()
    )

    if (
        config.slippage_bps < 0
        or config.fee_per_trade < 0
    ):
        raise Model2ExecutionRiskError(
            "Slippage and fees cannot be negative."
        )

    reference_price = money(raw_price)
    slippage = (
        Decimal(str(config.slippage_bps))
        / Decimal("10000")
    )

    if order.side == OrderSide.BUY:
        projected_fill_price = money(
            reference_price * (Decimal("1") + slippage)
        )
    elif order.side == OrderSide.SELL:
        projected_fill_price = money(
            reference_price * (Decimal("1") - slippage)
        )
    else:
        raise Model2ExecutionRiskError(
            "Unsupported order side."
        )

    if projected_fill_price <= 0:
        raise Model2ExecutionRiskError(
            "Projected fill price must be positive."
        )

    # Preserve prices for existing holdings. The order
    # ticker uses this observation's actual reference
    # price, not a caller-supplied replacement.
    prices = dict(market_prices)
    prices[order.ticker] = reference_price

    engine = (
        risk_engine
        if risk_engine is not None
        else RiskEngine()
    )

    assessment = engine.assess(
        portfolio=portfolio,
        ticker=order.ticker,
        side=order.side,
        quantity=order.quantity,
        reference_price=projected_fill_price,
        market_prices=prices,
        estimated_fees=config.fee_per_trade,
    )

    return Model2ExecutionRiskResult(
        order_id=order.order_id,
        reference_price=reference_price,
        projected_fill_price=projected_fill_price,
        assessment=assessment,
        checked_at_utc=now,
    )