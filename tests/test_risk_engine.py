from decimal import Decimal

import pytest

from risk.risk_engine import (
    RiskCode,
    RiskConfig,
    RiskDecision,
    RiskEngine,
)
from trading.orders import OrderSide
from trading.portfolio import Portfolio


def make_engine():

    return RiskEngine(
        RiskConfig(
            max_position_allocation=Decimal("0.10"),
            max_invested_allocation=Decimal("0.70"),
            minimum_cash_reserve=Decimal("0.30"),
            max_open_positions=10,
            allow_shorting=False,
        )
    )


def test_small_buy_is_approved():

    portfolio = Portfolio(
        10_000
    )

    engine = make_engine()

    assessment = engine.assess(
        portfolio=portfolio,
        ticker="AAPL",
        side=OrderSide.BUY,
        quantity=5,
        reference_price=100,
        market_prices={},
    )

    assert assessment.decision == (
        RiskDecision.APPROVE
    )

    assert assessment.approved is True


def test_position_limit_is_enforced():

    portfolio = Portfolio(
        10_000
    )

    engine = make_engine()

    assessment = engine.assess(
        portfolio=portfolio,
        ticker="AAPL",
        side=OrderSide.BUY,
        quantity=20,
        reference_price=100,
        market_prices={},
    )

    assert assessment.approved is False

    codes = {
        issue.code
        for issue in assessment.issues
    }

    assert (
        RiskCode.POSITION_LIMIT_EXCEEDED
        in codes
    )


def test_insufficient_cash_is_rejected():

    portfolio = Portfolio(
        1_000
    )

    engine = make_engine()

    assessment = engine.assess(
        portfolio=portfolio,
        ticker="AAPL",
        side=OrderSide.BUY,
        quantity=20,
        reference_price=100,
        market_prices={},
    )

    codes = {
        issue.code
        for issue in assessment.issues
    }

    assert RiskCode.INSUFFICIENT_CASH in codes


def test_cash_reserve_is_enforced():

    portfolio = Portfolio(
        10_000
    )

    engine = RiskEngine(
        RiskConfig(
            max_position_allocation=Decimal("1"),
            max_invested_allocation=Decimal("1"),
            minimum_cash_reserve=Decimal("0.30"),
            max_open_positions=10,
        )
    )

    assessment = engine.assess(
        portfolio=portfolio,
        ticker="AAPL",
        side=OrderSide.BUY,
        quantity=80,
        reference_price=100,
        market_prices={},
    )

    codes = {
        issue.code
        for issue in assessment.issues
    }

    assert (
        RiskCode.CASH_RESERVE_VIOLATION
        in codes
    )


def test_total_invested_limit_is_enforced():

    portfolio = Portfolio(
        10_000
    )

    portfolio.buy(
        "MSFT",
        30,
        100,
    )

    portfolio.buy(
        "GOOGL",
        30,
        100,
    )

    engine = RiskEngine(
        RiskConfig(
            max_position_allocation=Decimal("1"),
            max_invested_allocation=Decimal("0.70"),
            minimum_cash_reserve=Decimal("0"),
            max_open_positions=10,
        )
    )

    assessment = engine.assess(
        portfolio=portfolio,
        ticker="AAPL",
        side=OrderSide.BUY,
        quantity=20,
        reference_price=100,
        market_prices={
            "MSFT": 100,
            "GOOGL": 100,
        },
    )

    codes = {
        issue.code
        for issue in assessment.issues
    }

    assert (
        RiskCode.INVESTED_CAPITAL_LIMIT_EXCEEDED
        in codes
    )


def test_new_position_limit_is_enforced():

    portfolio = Portfolio(
        10_000
    )

    portfolio.buy(
        "AAPL",
        1,
        100,
    )

    engine = RiskEngine(
        RiskConfig(
            max_position_allocation=Decimal("1"),
            max_invested_allocation=Decimal("1"),
            minimum_cash_reserve=Decimal("0"),
            max_open_positions=1,
        )
    )

    assessment = engine.assess(
        portfolio=portfolio,
        ticker="MSFT",
        side=OrderSide.BUY,
        quantity=1,
        reference_price=100,
        market_prices={
            "AAPL": 100,
        },
    )

    codes = {
        issue.code
        for issue in assessment.issues
    }

    assert (
        RiskCode.MAX_OPEN_POSITIONS_EXCEEDED
        in codes
    )


def test_adding_to_existing_position_does_not_trigger_open_position_limit():

    portfolio = Portfolio(
        10_000
    )

    portfolio.buy(
        "AAPL",
        1,
        100,
    )

    engine = RiskEngine(
        RiskConfig(
            max_position_allocation=Decimal("1"),
            max_invested_allocation=Decimal("1"),
            minimum_cash_reserve=Decimal("0"),
            max_open_positions=1,
        )
    )

    assessment = engine.assess(
        portfolio=portfolio,
        ticker="AAPL",
        side=OrderSide.BUY,
        quantity=1,
        reference_price=100,
        market_prices={
            "AAPL": 100,
        },
    )

    assert assessment.approved is True


def test_valid_sell_is_approved():

    portfolio = Portfolio(
        10_000
    )

    portfolio.buy(
        "AAPL",
        10,
        100,
    )

    engine = make_engine()

    assessment = engine.assess(
        portfolio=portfolio,
        ticker="AAPL",
        side=OrderSide.SELL,
        quantity=5,
        reference_price=110,
        market_prices={
            "AAPL": 110,
        },
    )

    assert assessment.approved is True


def test_sell_without_position_is_rejected():

    portfolio = Portfolio(
        10_000
    )

    engine = make_engine()

    assessment = engine.assess(
        portfolio=portfolio,
        ticker="AAPL",
        side=OrderSide.SELL,
        quantity=1,
        reference_price=100,
        market_prices={},
    )

    codes = {
        issue.code
        for issue in assessment.issues
    }

    assert (
        RiskCode.INSUFFICIENT_SHARES
        in codes
    )


def test_shorting_is_rejected():

    portfolio = Portfolio(
        10_000
    )

    portfolio.buy(
        "AAPL",
        5,
        100,
    )

    engine = make_engine()

    assessment = engine.assess(
        portfolio=portfolio,
        ticker="AAPL",
        side=OrderSide.SELL,
        quantity=10,
        reference_price=100,
        market_prices={
            "AAPL": 100,
        },
    )

    codes = {
        issue.code
        for issue in assessment.issues
    }

    assert (
        RiskCode.SHORTING_NOT_ALLOWED
        in codes
    )


def test_missing_existing_position_price_fails_closed():

    portfolio = Portfolio(
        10_000
    )

    portfolio.buy(
        "MSFT",
        5,
        100,
    )

    engine = make_engine()

    assessment = engine.assess(
        portfolio=portfolio,
        ticker="AAPL",
        side=OrderSide.BUY,
        quantity=1,
        reference_price=100,
        market_prices={},
    )

    assert assessment.approved is False

    codes = {
        issue.code
        for issue in assessment.issues
    }

    assert (
        RiskCode.MISSING_MARKET_PRICE
        in codes
    )


def test_invalid_config_is_rejected():

    with pytest.raises(
        ValueError
    ):
        RiskEngine(
            RiskConfig(
                max_position_allocation=Decimal(
                    "1.5"
                )
            )
        )