from __future__ import annotations

from trading.orders import OrderSide

from datetime import (
    date,
    datetime,
    timezone,
)
from decimal import Decimal

import pandas as pd
import pytest

import runtime
from services.data_quality import (
    DataQualityReport,
)
from services.market_data import (
    MarketDataResult,
)


EXECUTION_SESSION = date(
    2026,
    9,
    14,
)


class FakeExecutionProvider:

    def __init__(
        self,
        execution_session,
    ) -> None:

        self.execution_session = (
            execution_session
        )

        self.calls = []

    def get_market_data(
        self,
        ticker,
    ):

        normalized = (
            ticker.strip().upper()
        )

        self.calls.append(
            normalized
        )

        data = pd.DataFrame(
            {
                "Open": [
                    100.0
                ],
                "High": [
                    101.0
                ],
                "Low": [
                    99.0
                ],
                "Close": [
                    100.5
                ],
                "Adj Close": [
                    100.5
                ],
                "Volume": [
                    100_000
                ],
            },
            index=pd.to_datetime(
                [
                    self.execution_session
                    .isoformat()
                ]
            ),
        )

        return MarketDataResult(
            ticker=normalized,
            data=data,
            provider="fake-execution",
            retrieved_at_utc=datetime(
                2026,
                9,
                14,
                13,
                31,
                tzinfo=timezone.utc,
            ),
        )

    def build_quality_report(
        self,
        result,
    ):

        return DataQualityReport(
            ticker=result.ticker,
            checked_at_utc=(
                result.retrieved_at_utc
            ),
            latest_data_session=(
                self.execution_session
            ),
            latest_expected_completed_session=(
                self.execution_session
            ),
            issues=(),
        )

    @staticmethod
    def observation_time(
        result,
    ):

        return result.retrieved_at_utc


class FakeExecutionProviderFactory:

    def __init__(
        self,
    ) -> None:

        self.sessions = []
        self.providers = []

    def __call__(
        self,
        execution_session,
    ):

        self.sessions.append(
            execution_session
        )

        provider = FakeExecutionProvider(
            execution_session
        )

        self.providers.append(
            provider
        )

        return provider


def test_default_ticker_universe(
    monkeypatch,
):

    monkeypatch.delenv(
        "PAPER_TRADING_TICKERS",
        raising=False,
    )

    assert (
        runtime._load_tickers()
        == runtime.DEFAULT_TICKERS
    )


def test_custom_ticker_universe(
    monkeypatch,
):

    monkeypatch.setenv(
        "PAPER_TRADING_TICKERS",
        "aapl, msft, AAPL, nvda",
    )

    assert (
        runtime._load_tickers()
        == (
            "AAPL",
            "MSFT",
            "NVDA",
        )
    )


def test_blank_custom_tickers_rejected(
    monkeypatch,
):

    monkeypatch.setenv(
        "PAPER_TRADING_TICKERS",
        " , , ",
    )

    with pytest.raises(
        ValueError
    ):

        runtime._load_tickers()


def test_default_starting_cash(
    monkeypatch,
):

    monkeypatch.delenv(
        "PAPER_TRADING_STARTING_CASH",
        raising=False,
    )

    assert (
        runtime._load_starting_cash()
        == Decimal(
            "10000"
        )
    )


def test_custom_starting_cash(
    monkeypatch,
):

    monkeypatch.setenv(
        "PAPER_TRADING_STARTING_CASH",
        "25000"
    )

    assert (
        runtime._load_starting_cash()
        == Decimal(
            "25000"
        )
    )


def test_nonpositive_starting_cash_rejected(
    monkeypatch,
):

    monkeypatch.setenv(
        "PAPER_TRADING_STARTING_CASH",
        "0"
    )

    with pytest.raises(
        ValueError
    ):

        runtime._load_starting_cash()


def test_default_model_version(
    monkeypatch,
):

    monkeypatch.delenv(
        "PAPER_TRADING_MODEL_VERSION",
        raising=False,
    )

    assert (
        runtime._load_model_version()
        == "model-1"
    )


def test_blank_model_version_rejected(
    monkeypatch,
):

    monkeypatch.setenv(
        "PAPER_TRADING_MODEL_VERSION",
        "   "
    )

    with pytest.raises(
        ValueError
    ):

        runtime._load_model_version()


def test_runtime_initializes_database(
    tmp_path,
):

    db = (
        tmp_path
        / "runtime.db"
    )

    live = (
        runtime.build_live_runtime(
            db
        )
    )

    assert (
        live.account_storage
        .count_accounts()
        == 1
    )

    assert (
        live.trading_storage
        .count_orders()
        == 0
    )

    assert (
        live.execution_attempt_storage
        .count_attempts()
        == 0
    )


def test_status_empty_database(
    tmp_path,
):

    db = (
        tmp_path
        / "runtime.db"
    )

    live = (
        runtime.build_live_runtime(
            db
        )
    )

    status = (
        live.get_status()
    )

    assert (
        status.total_orders
        == 0
    )

    assert (
        status.pending_orders
        == 0
    )

    assert (
        status.filled_orders
        == 0
    )

    assert (
        status.rejected_orders
        == 0
    )

    assert (
        status.total_fills
        == 0
    )

    assert (
        status.execution_attempts
        == 0
    )


def test_execution_with_no_orders_is_safe(
    tmp_path,
):

    db = (
        tmp_path
        / "runtime.db"
    )

    factory = (
        FakeExecutionProviderFactory()
    )

    live = (
        runtime.build_live_runtime(
            db,
            execution_provider_factory=(
                factory
            ),
        )
    )

    result = (
        live.run_execution(
            EXECUTION_SESSION
        )
    )

    assert (
        result.discovered_order_count
        == 0
    )

    assert (
        result.filled_orders
        == 0
    )


def test_execution_provider_receives_exact_session(
    tmp_path,
):

    db = (
        tmp_path
        / "runtime.db"
    )

    factory = (
        FakeExecutionProviderFactory()
    )

    live = (
        runtime.build_live_runtime(
            db,
            execution_provider_factory=(
                factory
            ),
        )
    )

    live.run_execution(
        EXECUTION_SESSION
    )

    assert (
        factory.sessions
        == [
            EXECUTION_SESSION
        ]
    )


def test_pending_order_can_complete_full_runtime_execution(
    tmp_path,
):

    db = (
        tmp_path
        / "runtime.db"
    )

    factory = (
        FakeExecutionProviderFactory()
    )

    live = (
        runtime.build_live_runtime(
            db,
            execution_provider_factory=(
                factory
            ),
        )
    )

    # Friday after close.
    signal_timestamp = datetime(
        2026,
        9,
        11,
        21,
        0,
        tzinfo=timezone.utc,
    )

    prepared = (
        live.execution_service
        .prepare_order(
            ticker="AAPL",
            side=OrderSide.BUY,
            quantity=1,
            signal_timestamp=(
                signal_timestamp
            ),
            model_version="model-1",
            order_id=(
                "runtime-execution-test"
            ),
        )
    )

    assert (
        prepared.order
        .execution_session
        == EXECUTION_SESSION
    )

    assert (
        live.trading_storage
        .count_orders()
        == 1
    )

    result = (
        live.run_execution(
            EXECUTION_SESSION
        )
    )

    assert (
        result.discovered_order_count
        == 1
    )

    assert (
        result.filled_orders
        == 1
    )

    assert (
        result.rejected_orders
        == 0
    )

    assert (
        result.failed_orders
        == 0
    )

    assert (
        live.trading_storage
        .count_fills()
        == 1
    )

    assert (
        live.execution_attempt_storage
        .count_attempts()
        == 1
    )