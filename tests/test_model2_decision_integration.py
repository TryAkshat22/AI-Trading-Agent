
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pandas as pd
import pytest

from database.account_storage import AccountStorage
from database.storage import MarketDataStorage
from database.trading_storage import TradingStorage
from model2_config import (
    MODEL_2_ACCOUNT_ID,
    MODEL_2_VERSION,
)
from model2_decision_runner import (
    build_model2_decision_components,
)
from services.data_quality import DataQualityReport
from services.market_data import MarketDataResult
from trading.decision_execution_coordinator import (
    DecisionExecutionCoordinatorError,
)
from trading.decision_pipeline import DecisionStatus
from trading.orders import OrderSide


SOURCE_SESSION = date(2026, 9, 4)

DECISION_TIME = datetime(
    2026, 9, 4, 21, 10,
    tzinfo=timezone.utc,
)

ORDER_ID = (
    "model-2-flexible-2026-09-04-AAPL"
)


def make_market_result() -> MarketDataResult:
    data = pd.DataFrame(
        {
            "Open": [100.0],
            "High": [102.0],
            "Low": [99.0],
            "Close": [101.0],
            "Adj Close": [101.0],
            "Volume": [1_000_000],
        },
        index=pd.to_datetime(["2026-09-04"]),
    )

    return MarketDataResult(
        ticker="AAPL",
        data=data,
        provider="integration-test",
        retrieved_at_utc=datetime(
            2026, 9, 4, 21, 5,
            tzinfo=timezone.utc,
        ),
    )


def make_quality_report() -> DataQualityReport:
    return DataQualityReport(
        ticker="AAPL",
        checked_at_utc=datetime(
            2026, 9, 4, 21, 6,
            tzinfo=timezone.utc,
        ),
        latest_data_session=SOURCE_SESSION,
        latest_expected_completed_session=SOURCE_SESSION,
        issues=(),
    )


class ControlledApprovedPipeline:
    """
    Supplies a controlled approved decision so these
    tests exercise actual order persistence rather than
    depending on a historical indicator calculation.
    """

    def __init__(self):
        self.calls = 0

    def evaluate(
        self,
        market_result,
        quality_report,
        **kwargs,
    ):
        self.calls += 1

        return SimpleNamespace(
            ticker=market_result.ticker,
            status=DecisionStatus.BUY_APPROVED,
            signal=SimpleNamespace(
                ticker=market_result.ticker,
                source_session=SOURCE_SESSION,
            ),
            side=OrderSide.BUY,
            quantity=1,
        )


def make_isolated_components(
    tmp_path,
    monkeypatch,
):
    model1_path = tmp_path / "model1.db"
    model2_path = tmp_path / "model2.db"

    monkeypatch.setenv(
        "TRADING_AGENT_DB_PATH",
        str(model1_path),
    )
    monkeypatch.setenv(
        "PAPER_TRADING_MODEL2_DB_PATH",
        str(model2_path),
    )

    model2_accounts = AccountStorage(
        model2_path
    )
    model2_trading = TradingStorage(
        model2_path
    )

    model2_accounts.initialize()
    model2_trading.initialize()

    model2_accounts.create_account(
        starting_cash=10000,
        account_id=MODEL_2_ACCOUNT_ID,
    )

    components = build_model2_decision_components()

    # Decision snapshots require the market-data schema.
    components.market_storage.initialize()

    controlled_pipeline = ControlledApprovedPipeline()

    components.orchestrator.decision_pipeline = (
        controlled_pipeline
    )

    return (
        model1_path,
        model2_path,
        components,
        controlled_pipeline,
    )


def test_approved_decision_persists_model2_order_and_lineage(
    tmp_path,
    monkeypatch,
):
    (
        model1_path,
        model2_path,
        components,
        pipeline,
    ) = make_isolated_components(
        tmp_path,
        monkeypatch,
    )

    result = components.orchestrator.run(
        market_result=make_market_result(),
        quality_report=make_quality_report(),
        decision_timestamp=DECISION_TIME,
        decision_kwargs={
            "market_prices": {
                "AAPL": Decimal("101"),
            },
        },
        order_id=ORDER_ID,
    )

    stored = components.context.trading_storage.get_order(
        ORDER_ID
    )

    assert result.order_created
    assert stored is not None
    assert stored.status == "PENDING"
    assert stored.ticker == "AAPL"
    assert stored.model_version == MODEL_2_VERSION
    assert stored.decision_run_id == result.decision_run_id

    expected_session = (
        components.execution_service.scheduler
        .create_plan(DECISION_TIME)
        .execution_session
    )

    assert stored.execution_session == expected_session

    assert (
        components.context.trading_storage.count_orders()
        == 1
    )
    assert (
        components.context.trading_storage.count_fills()
        == 0
    )
    assert pipeline.calls == 1
    assert not model1_path.exists()


def test_repeated_order_id_cannot_create_second_order(
    tmp_path,
    monkeypatch,
):
    (
        _,
        _,
        components,
        _,
    ) = make_isolated_components(
        tmp_path,
        monkeypatch,
    )

    arguments = {
        "market_result": make_market_result(),
        "quality_report": make_quality_report(),
        "decision_timestamp": DECISION_TIME,
        "decision_kwargs": {
            "market_prices": {
                "AAPL": Decimal("101"),
            },
        },
        "order_id": ORDER_ID,
    }

    first = components.orchestrator.run(
        **arguments
    )

    assert first.order_created

    with pytest.raises(Exception):
        components.orchestrator.run(
            **arguments
        )

    trading = components.context.trading_storage

    assert trading.count_orders() == 1
    assert trading.count_fills() == 0


def test_batch_reports_duplicate_without_creating_another_order(
    tmp_path,
    monkeypatch,
):
    (
        _,
        _,
        components,
        _,
    ) = make_isolated_components(
        tmp_path,
        monkeypatch,
    )

    # Use one ticker and controlled data. No network calls.
    components.batch_runner.tickers = ("AAPL",)
    components.batch_runner.market_data_fetcher = (
        lambda ticker: make_market_result()
    )
    components.batch_runner.quality_report_builder = (
        lambda result: make_quality_report()
    )

    arguments = {
        "decision_timestamp": DECISION_TIME,
        "market_prices": {
            "AAPL": Decimal("101"),
        },
        "order_id_factory": lambda ticker: ORDER_ID,
    }

    first = components.decision_runner.run(
        **arguments
    )

    second = components.decision_runner.run(
        **arguments
    )

    assert first.orders_created == 1
    assert first.failed_tickers == 0

    assert second.orders_created == 0
    assert second.failed_tickers == 1

    assert (
        components.context.trading_storage.count_orders()
        == 1
    )
    assert (
        components.context.trading_storage.count_fills()
        == 0
    )


def test_calendar_disagreement_persists_no_order(
    tmp_path,
    monkeypatch,
):
    (
        _,
        _,
        components,
        _,
    ) = make_isolated_components(
        tmp_path,
        monkeypatch,
    )

    actual_session = (
        components.execution_service.scheduler
        .create_plan(DECISION_TIME)
        .execution_session
    )

    class DisagreeingTimestampValidator:
        def validate(
            self,
            source_session,
            decision_timestamp,
        ):
            assert source_session == SOURCE_SESSION

            return SimpleNamespace(
                decision_timestamp_utc=DECISION_TIME,
                next_execution_session=date(
                    actual_session.year,
                    actual_session.month,
                    actual_session.day,
                ).replace(
                    day=actual_session.day + 1
                ),
            )

    components.coordinator.timestamp_validator = (
        DisagreeingTimestampValidator()
    )

    with pytest.raises(
        DecisionExecutionCoordinatorError,
        match="No order was prepared",
    ):
        components.orchestrator.run(
            market_result=make_market_result(),
            quality_report=make_quality_report(),
            decision_timestamp=DECISION_TIME,
            decision_kwargs={
                "market_prices": {
                    "AAPL": Decimal("101"),
                },
            },
            order_id=ORDER_ID,
        )

    trading = components.context.trading_storage

    assert trading.count_orders() == 0
    assert trading.count_fills() == 0