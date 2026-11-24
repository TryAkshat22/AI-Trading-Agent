from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from model2_execution_risk import (
    Model2ExecutionRiskError,
    assess_model2_execution_risk,
)
from risk.risk_engine import RiskDecision, RiskCode
from trading.flexible_execution_observation import (
    FlexibleExecutionObservation,
)
from trading.orders import Order, OrderSide
from trading.portfolio import Portfolio


SESSION = date(2026, 9, 18)

NOW = datetime(
    2026, 9, 18, 13, 46, 10,
    tzinfo=timezone.utc,
)


def make_order(quantity=2):
    return Order(
        order_id="risk-test-AAPL",
        ticker="AAPL",
        side=OrderSide.BUY,
        quantity=quantity,
        signal_timestamp_utc=datetime(
            2026, 9, 17, 20, 45,
            tzinfo=timezone.utc,
        ),
        execution_session=SESSION,
    )


def make_observation():
    start = datetime(
        2026, 9, 18, 13, 45,
        tzinfo=timezone.utc,
    )

    return FlexibleExecutionObservation(
        ticker="AAPL",
        execution_session=SESSION,
        reference_price=101.0,
        price_field="Close",
        provider="controlled-test",
        bar_start_utc=start,
        bar_end_utc=start + timedelta(minutes=1),
        retrieved_at_utc=datetime(
            2026, 9, 18, 13, 46, 5,
            tzinfo=timezone.utc,
        ),
        execution_checked_at_utc=NOW,
        model="flexible-observed-close-v1",
    )


def evaluate(
    *,
    portfolio=None,
    quantity=2,
    market_prices=None,
    now=NOW,
):
    return assess_model2_execution_risk(
        order=make_order(quantity),
        observation=make_observation(),
        portfolio=(
            portfolio
            if portfolio is not None
            else Portfolio(starting_cash=10000)
        ),
        market_prices=(
            market_prices
            if market_prices is not None
            else {}
        ),
        clock=lambda: now,
    )


def test_approved_trade_uses_slippage_adjusted_price():
    portfolio = Portfolio(starting_cash=10000)

    result = evaluate(portfolio=portfolio)

    assert result.reference_price == Decimal("101.00")
    assert result.projected_fill_price == Decimal("101.05")
    assert result.assessment.decision == RiskDecision.APPROVE

    # Risk assessment must not modify holdings or cash.
    assert portfolio.cash == 10000
    assert portfolio.positions == {}


def test_missing_price_for_existing_holding_is_rejected():
    portfolio = Portfolio(starting_cash=10000)
    portfolio.buy("MSFT", 1, 100)

    result = evaluate(
        portfolio=portfolio,
        market_prices={},
    )

    assert result.assessment.decision == RiskDecision.REJECT
    assert any(
        issue.code == RiskCode.MISSING_MARKET_PRICE
        for issue in result.assessment.issues
    )


def test_existing_holding_with_price_can_be_valued():
    portfolio = Portfolio(starting_cash=10000)
    portfolio.buy("MSFT", 1, 100)

    result = evaluate(
        portfolio=portfolio,
        market_prices={"MSFT": 100},
    )

    assert result.assessment.decision == RiskDecision.APPROVE


def test_position_concentration_is_rejected():
    result = evaluate(quantity=11)

    assert result.assessment.decision == RiskDecision.REJECT
    assert any(
        issue.code == RiskCode.POSITION_LIMIT_EXCEEDED
        for issue in result.assessment.issues
    )


def test_stale_observation_is_blocked():
    with pytest.raises(
        Model2ExecutionRiskError,
        match="stale",
    ):
        evaluate(
            now=datetime(
                2026, 9, 18, 13, 52,
                tzinfo=timezone.utc,
            )
        )


def test_closed_execution_window_is_blocked():
    with pytest.raises(
        Exception,
        match="Outside the Model 2 execution window",
    ):
        evaluate(
            now=datetime(
                2026, 9, 18, 19, 30,
                tzinfo=timezone.utc,
            )
        )