from datetime import date, datetime, timezone
from decimal import Decimal

import pandas as pd

from database.account_storage import AccountStorage
from database.trading_storage import TradingStorage
from risk.position_sizer import (
    PositionSizer,
    PositionSizerConfig,
)
from risk.risk_engine import (
    RiskConfig,
    RiskEngine,
)
from services.data_quality import DataQualityReport
from services.market_data import MarketDataResult
from trading.decision_pipeline import (
    DecisionPipeline,
    DecisionStatus,
)
from trading.orders import (
    Fill,
    Order,
    OrderSide,
    OrderStatus,
)
from trading.portfolio import money


def make_market_result(
    closes,
):

    dates = pd.bdate_range(
        start="2026-05-01",
        periods=len(closes),
    )

    data = pd.DataFrame(
        {
            "Open": closes,
            "High": [
                value + 1
                for value in closes
            ],
            "Low": [
                value - 1
                for value in closes
            ],
            "Close": closes,
            "Adj Close": closes,
            "Volume": [
                1_000_000
                for _ in closes
            ],
        },
        index=dates,
    )

    return MarketDataResult(
        ticker="AAPL",
        data=data,
        provider="test",
        retrieved_at_utc=datetime(
            2026,
            9,
            9,
            tzinfo=timezone.utc,
        ),
    )


def make_report(
    result,
):

    latest = (
        result.data.index[-1].date()
    )

    return DataQualityReport(
        ticker="AAPL",
        checked_at_utc=datetime(
            2026,
            9,
            9,
            tzinfo=timezone.utc,
        ),
        latest_data_session=latest,
        latest_expected_completed_session=latest,
        issues=(),
    )


def make_pipeline(
    tmp_path,
    starting_cash=10_000,
):

    db = tmp_path / "test.db"

    accounts = AccountStorage(db)
    trades = TradingStorage(db)

    accounts.initialize()
    trades.initialize()

    accounts.create_account(
        starting_cash
    )

    pipeline = DecisionPipeline(
        account_storage=accounts,
        trading_storage=trades,
    )

    return pipeline, accounts, trades


def add_existing_position(
    trades,
    quantity=5,
    price=100,
):

    order = Order(
        order_id="existing-buy",
        ticker="AAPL",
        side=OrderSide.BUY,
        quantity=quantity,
        signal_timestamp_utc=datetime(
            2026,
            9,
            1,
            21,
            0,
            tzinfo=timezone.utc,
        ),
        execution_session=date(
            2026,
            9,
            2,
        ),
    )

    fill = Fill(
        order_id="existing-buy",
        ticker="AAPL",
        side=OrderSide.BUY,
        quantity=quantity,
        reference_price=money(price),
        fill_price=money(price),
        gross_value=money(
            quantity * price
        ),
        fees=money(0),
        slippage_cost=money(0),
        execution_session=date(
            2026,
            9,
            2,
        ),
        status=OrderStatus.FILLED,
        realized_pnl=money(0),
    )

    trades.save_order(order)
    trades.save_fill(fill)


def test_bullish_stock_is_approved_for_buy(
    tmp_path,
):

    pipeline, _, _ = make_pipeline(
        tmp_path
    )

    result = make_market_result(
        list(range(100, 180))
    )

    decision = pipeline.evaluate(
        market_result=result,
        quality_report=make_report(result),
        market_prices={},
    )

    assert (
        decision.status
        == DecisionStatus.BUY_APPROVED
    )

    assert decision.side == OrderSide.BUY
    assert decision.quantity > 0
    assert decision.approved_for_order is True


def test_bearish_stock_returns_no_trade(
    tmp_path,
):

    pipeline, _, _ = make_pipeline(
        tmp_path
    )

    result = make_market_result(
        list(range(200, 120, -1))
    )

    decision = pipeline.evaluate(
        market_result=result,
        quality_report=make_report(result),
        market_prices={},
    )

    assert (
        decision.status
        == DecisionStatus.NO_TRADE
    )

    assert decision.quantity == 0
    assert decision.approved_for_order is False


def test_existing_bullish_position_holds(
    tmp_path,
):

    pipeline, _, trades = make_pipeline(
        tmp_path
    )

    add_existing_position(
        trades,
        quantity=5,
        price=100,
    )

    result = make_market_result(
        list(range(100, 180))
    )

    decision = pipeline.evaluate(
        market_result=result,
        quality_report=make_report(result),
        market_prices={
            "AAPL": 179,
        },
    )

    assert (
        decision.status
        == DecisionStatus.HOLD
    )

    assert decision.quantity == 0


def test_existing_bearish_position_exits(
    tmp_path,
):

    pipeline, _, trades = make_pipeline(
        tmp_path
    )

    add_existing_position(
        trades,
        quantity=5,
        price=100,
    )

    result = make_market_result(
        list(range(200, 120, -1))
    )

    decision = pipeline.evaluate(
        market_result=result,
        quality_report=make_report(result),
        market_prices={
            "AAPL": 121,
        },
    )

    assert (
        decision.status
        == DecisionStatus.EXIT_APPROVED
    )

    assert decision.side == OrderSide.SELL

    # EXIT should liquidate the full position.
    assert decision.quantity == 5

    assert decision.approved_for_order is True


def test_expensive_stock_can_produce_size_zero(
    tmp_path,
):

    pipeline, _, _ = make_pipeline(
        tmp_path,
        starting_cash=1_000,
    )

    pipeline.position_sizer = PositionSizer(
        PositionSizerConfig(
            max_position_allocation=(
                Decimal("0.10")
            )
        )
    )

    closes = [
        2_000 + number
        for number in range(80)
    ]

    result = make_market_result(
        closes
    )

    decision = pipeline.evaluate(
        market_result=result,
        quality_report=make_report(result),
        market_prices={},
    )

    assert (
        decision.status
        == DecisionStatus.SIZE_ZERO
    )

    assert decision.quantity == 0


def test_risk_engine_can_reject_sized_buy(
    tmp_path,
):

    pipeline, _, _ = make_pipeline(
        tmp_path
    )

    # Position sizer allows up to 20%.
    pipeline.position_sizer = PositionSizer(
        PositionSizerConfig(
            max_position_allocation=(
                Decimal("0.20")
            )
        )
    )

    # Risk engine allows only 5%.
    pipeline.risk_engine = RiskEngine(
        RiskConfig(
            max_position_allocation=(
                Decimal("0.05")
            ),
            max_invested_allocation=(
                Decimal("0.70")
            ),
            minimum_cash_reserve=(
                Decimal("0.30")
            ),
            max_open_positions=10,
        )
    )

    result = make_market_result(
        list(range(100, 180))
    )

    decision = pipeline.evaluate(
        market_result=result,
        quality_report=make_report(result),
        market_prices={},
    )

    assert (
        decision.status
        == DecisionStatus.RISK_REJECTED
    )

    assert decision.risk_assessment is not None

    assert (
        decision.risk_assessment.approved
        is False
    )


def test_pipeline_derives_position_state_automatically(
    tmp_path,
):

    pipeline, _, trades = make_pipeline(
        tmp_path
    )

    add_existing_position(
        trades,
        quantity=3,
        price=100,
    )

    result = make_market_result(
        list(range(100, 180))
    )

    decision = pipeline.evaluate(
        market_result=result,
        quality_report=make_report(result),
        market_prices={
            "AAPL": 179,
        },
    )

    # No has_position argument was supplied.
    # Pipeline discovered the position from SQLite.
    assert (
        decision.status
        == DecisionStatus.HOLD
    )


def test_pipeline_does_not_create_orders(
    tmp_path,
):

    pipeline, _, trades = make_pipeline(
        tmp_path
    )

    result = make_market_result(
        list(range(100, 180))
    )

    decision = pipeline.evaluate(
        market_result=result,
        quality_report=make_report(result),
        market_prices={},
    )

    assert decision.approved_for_order is True

    # Decision layer must not execute or persist orders.
    assert trades.count_orders() == 0
    assert trades.count_fills() == 0