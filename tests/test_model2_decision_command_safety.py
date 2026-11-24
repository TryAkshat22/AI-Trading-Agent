
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


def make_market_result(
    ticker: str,
    *,
    include_close: bool = True,
) -> MarketDataResult:
    columns = {
        "Open": [100.0],
        "High": [102.0],
        "Low": [99.0],
        "Volume": [1_000_000],
    }

    if include_close:
        columns["Close"] = [101.0]
        columns["Adj Close"] = [101.0]

    return MarketDataResult(
        ticker=ticker,
        data=pd.DataFrame(
            columns,
            index=pd.to_datetime(["2026-09-16"]),
        ),
        provider="safety-test",
        retrieved_at_utc=datetime(
            2026, 9, 16, 20, 16,
            tzinfo=timezone.utc,
        ),
    )


def make_quality_report(
    ticker: str,
    *,
    latest_session: date = SESSION,
) -> DataQualityReport:
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


def make_components(
    tmp_path,
    monkeypatch,
):
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

    monkeypatch.setattr(
        "model2_decision_command."
        "build_model2_decision_components",
        lambda: components,
    )

    return model1, model2, components


@pytest.mark.parametrize(
    "bad_data",
    (
        "stale_session",
        "missing_close",
    ),
)
def test_bad_preflight_data_creates_no_orders(
    tmp_path,
    monkeypatch,
    bad_data,
):
    model1, model2, components = make_components(
        tmp_path,
        monkeypatch,
    )

    def fetch(ticker):
        return make_market_result(
            ticker,
            include_close=not (
                ticker == "MSFT"
                and bad_data == "missing_close"
            ),
        )

    def quality(result):
        latest_session = SESSION

        if (
            result.ticker == "MSFT"
            and bad_data == "stale_session"
        ):
            latest_session = date(2026, 9, 15)

        return make_quality_report(
            result.ticker,
            latest_session=latest_session,
        )

    components.batch_runner.market_data_fetcher = fetch
    components.batch_runner.quality_report_builder = quality

    with pytest.raises(
        Model2DecisionCommandError
    ):
        run_model2_decision(
            execute=True,
            now=AFTER_CLOSE,
        )

    trading = TradingStorage(model2)

    assert trading.count_orders() == 0
    assert trading.count_fills() == 0
    assert (
        components.market_storage.count_ingestion_runs()
        == 0
    )
    assert not model1.exists()


def test_partial_failure_is_reported_and_retry_is_blocked(
    tmp_path,
    monkeypatch,
):
    model1, model2, components = make_components(
        tmp_path,
        monkeypatch,
    )

    components.batch_runner.market_data_fetcher = (
        lambda ticker: make_market_result(ticker)
    )

    components.batch_runner.quality_report_builder = (
        lambda result: make_quality_report(
            result.ticker
        )
    )

    class ControlledPipeline:
        def __init__(self):
            self.calls = []

        def evaluate(
            self,
            market_result,
            quality_report,
            **kwargs,
        ):
            ticker = market_result.ticker
            self.calls.append(ticker)

            if ticker == "MSFT":
                raise RuntimeError(
                    "Controlled MSFT decision failure."
                )

            return SimpleNamespace(
                ticker=ticker,
                status=DecisionStatus.BUY_APPROVED,
                signal=SimpleNamespace(
                    ticker=ticker,
                    source_session=SESSION,
                ),
                side=OrderSide.BUY,
                quantity=1,
            )

    pipeline = ControlledPipeline()

    components.orchestrator.decision_pipeline = pipeline

    with pytest.raises(
        Model2DecisionCommandError,
        match="ticker decisions failed",
    ):
        run_model2_decision(
            execute=True,
            now=AFTER_CLOSE,
        )

    trading = TradingStorage(model2)

    expected_order_id = (
        "model-2-flexible-2026-09-16-AAPL"
    )

    saved_order = trading.get_order(
        expected_order_id
    )

    # A successful earlier ticker can remain saved
    # when a later ticker fails. The command must
    # report that partial outcome, not conceal it.
    assert saved_order is not None
    assert saved_order.status == "PENDING"
    assert saved_order.model_version == (
        "model-2-flexible"
    )
    assert saved_order.decision_run_id is not None

    assert trading.count_orders() == 1
    assert trading.count_fills() == 0

    assert pipeline.calls == [
        "AAPL",
        "MSFT",
    ]

    # A second invocation must stop at the existing
    # order check, before evaluating either ticker.
    with pytest.raises(
        Model2DecisionCommandError,
        match="already exists",
    ):
        run_model2_decision(
            execute=True,
            now=AFTER_CLOSE,
        )

    assert pipeline.calls == [
        "AAPL",
        "MSFT",
    ]

    assert trading.count_orders() == 1
    assert trading.count_fills() == 0
    assert not model1.exists()