
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pandas as pd
import pytest

from database.account_storage import AccountStorage
from database.trading_storage import TradingStorage
from model2_config import MODEL_2_ACCOUNT_ID
from model2_decision_command import (
    Model2DecisionCommandError,
    run_model2_decision,
)
from model2_decision_ledger import Model2DecisionLedger
from model2_decision_runner import (
    build_model2_decision_components,
)
from services.data_quality import DataQualityReport
from services.market_data import MarketDataResult
from trading.decision_pipeline import DecisionStatus
from trading.orders import OrderSide


SESSION = date(2026, 9, 16)

AFTER_CLOSE = datetime(
    2026, 9, 16, 21, 10,
    tzinfo=timezone.utc,
)


def market_result(ticker):
    return MarketDataResult(
        ticker=ticker,
        data=pd.DataFrame(
            {
                "Open": [100.0],
                "High": [102.0],
                "Low": [99.0],
                "Close": [101.0],
                "Adj Close": [101.0],
                "Volume": [1_000_000],
            },
            index=pd.to_datetime(["2026-09-16"]),
        ),
        provider="ledger-integration-test",
        retrieved_at_utc=datetime(
            2026, 9, 16, 20, 16,
            tzinfo=timezone.utc,
        ),
    )


def quality_report(ticker, latest_session=SESSION):
    return DataQualityReport(
        ticker=ticker,
        checked_at_utc=datetime(
            2026, 9, 16, 20, 17,
            tzinfo=timezone.utc,
        ),
        latest_data_session=latest_session,
        latest_expected_completed_session=SESSION,
        issues=(),
    )


def setup_components(tmp_path, monkeypatch):
    model1 = tmp_path / "model1.db"
    model2 = tmp_path / "model2.db"

    monkeypatch.setenv(
        "TRADING_AGENT_DB_PATH",
        str(model1),
    )
    monkeypatch.setenv(
        "PAPER_TRADING_MODEL2_DB_PATH",
        str(model2),
    )

    accounts = AccountStorage(model2)
    trading = TradingStorage(model2)

    accounts.initialize()
    trading.initialize()

    accounts.create_account(
        starting_cash=Decimal("10000"),
        account_id=MODEL_2_ACCOUNT_ID,
    )

    components = build_model2_decision_components()
    components.market_storage.initialize()

    components.batch_runner.tickers = (
        "AAPL",
        "MSFT",
    )

    components.batch_runner.market_data_fetcher = (
        market_result
    )

    components.batch_runner.quality_report_builder = (
        lambda result: quality_report(result.ticker)
    )

    monkeypatch.setattr(
        "model2_decision_command."
        "build_model2_decision_components",
        lambda: components,
    )

    return model1, model2, components


def test_zero_order_run_is_recorded_and_cannot_repeat(
    tmp_path,
    monkeypatch,
):
    model1, model2, components = setup_components(
        tmp_path,
        monkeypatch,
    )

    class HoldPipeline:
        def evaluate(
            self,
            market_result,
            quality_report,
            **kwargs,
        ):
            return SimpleNamespace(
                ticker=market_result.ticker,
                status=DecisionStatus.HOLD,
            )

    components.orchestrator.decision_pipeline = (
        HoldPipeline()
    )

    result = run_model2_decision(
        execute=True,
        now=AFTER_CLOSE,
    )

    assert result.orders_created == 0
    assert result.failed_tickers == 0

    ledger = Model2DecisionLedger(model2)
    record = ledger.get_for_session(SESSION)

    assert record is not None
    assert record.status == "COMPLETED"
    assert record.orders_created == 0
    assert record.failed_tickers == 0

    assert TradingStorage(model2).count_orders() == 0
    assert TradingStorage(model2).count_fills() == 0
    assert not model1.exists()

    with pytest.raises(
        Model2DecisionCommandError,
        match="COMPLETED ledger record",
    ):
        run_model2_decision(
            execute=True,
            now=AFTER_CLOSE,
        )


def test_partial_failure_is_recorded_and_blocks_retry(
    tmp_path,
    monkeypatch,
):
    model1, model2, components = setup_components(
        tmp_path,
        monkeypatch,
    )

    class PartialFailurePipeline:
        def evaluate(
            self,
            market_result,
            quality_report,
            **kwargs,
        ):
            if market_result.ticker == "MSFT":
                raise RuntimeError(
                    "Controlled MSFT failure."
                )

            return SimpleNamespace(
                ticker=market_result.ticker,
                status=DecisionStatus.BUY_APPROVED,
                signal=SimpleNamespace(
                    ticker=market_result.ticker,
                    source_session=SESSION,
                ),
                side=OrderSide.BUY,
                quantity=1,
            )

    components.orchestrator.decision_pipeline = (
        PartialFailurePipeline()
    )

    with pytest.raises(
        Model2DecisionCommandError,
        match="ticker decisions failed",
    ):
        run_model2_decision(
            execute=True,
            now=AFTER_CLOSE,
        )

    ledger = Model2DecisionLedger(model2)
    record = ledger.get_for_session(SESSION)

    assert record is not None
    assert record.status == "FAILED"
    assert record.orders_created == 1
    assert record.failed_tickers == 1

    trading = TradingStorage(model2)

    order = trading.get_order(
        "model-2-flexible-2026-09-16-AAPL"
    )

    assert order is not None
    assert order.status == "PENDING"
    assert trading.count_orders() == 1
    assert trading.count_fills() == 0
    assert not model1.exists()

    with pytest.raises(
        Model2DecisionCommandError,
        match="already exists",
    ):
        run_model2_decision(
            execute=True,
            now=AFTER_CLOSE,
        )

    assert trading.count_orders() == 1


def test_failed_preflight_does_not_claim_session(
    tmp_path,
    monkeypatch,
):
    model1, model2, components = setup_components(
        tmp_path,
        monkeypatch,
    )

    components.batch_runner.quality_report_builder = (
        lambda result: quality_report(
            result.ticker,
            latest_session=date(2026, 9, 15),
        )
    )

    with pytest.raises(
        Model2DecisionCommandError,
        match="completed-session data",
    ):
        run_model2_decision(
            execute=True,
            now=AFTER_CLOSE,
        )

    # The command must not even initialize the ledger
    # until market-data preflight has succeeded.
    ledger = Model2DecisionLedger(model2)
    ledger.initialize()

    assert ledger.get_for_session(SESSION) is None
    assert TradingStorage(model2).count_orders() == 0
    assert TradingStorage(model2).count_fills() == 0
    assert not model1.exists()


def test_readiness_detects_existing_zero_order_run(
    tmp_path,
    monkeypatch,
):
    _, model2, components = setup_components(
        tmp_path,
        monkeypatch,
    )

    ledger = Model2DecisionLedger(model2)
    ledger.initialize()

    claim = ledger.claim(
        SESSION,
        AFTER_CLOSE,
    )

    ledger.finish(
        claim.run_id,
        status="COMPLETED",
        finished_at=AFTER_CLOSE,
        orders_created=0,
        failed_tickers=0,
    )

    def unexpected_fetch(ticker):
        raise AssertionError(
            "Readiness must not fetch market data."
        )

    components.batch_runner.market_data_fetcher = (
        unexpected_fetch
    )

    with pytest.raises(
        Model2DecisionCommandError,
        match="COMPLETED ledger record",
    ):
        run_model2_decision(
            execute=False,
            now=AFTER_CLOSE,
        )

    assert TradingStorage(model2).count_orders() == 0