from __future__ import annotations

from datetime import (
    date,
    datetime,
    timezone,
)
from types import SimpleNamespace

import pandas as pd
import pytest

from services.data_quality import (
    DataQualityReport,
)
from services.market_data import (
    MarketDataResult,
)
from trading.daily_batch_runner import (
    DailyBatchRunner,
    DailyBatchRunnerError,
    InvalidTickerUniverseError,
)


def make_market_result(
    ticker: str,
) -> MarketDataResult:

    data = pd.DataFrame(
        {
            "Open": [100.0],
            "High": [101.0],
            "Low": [99.0],
            "Close": [100.0],
            "Adj Close": [100.0],
            "Volume": [1_000_000],
        },
        index=pd.to_datetime(
            [
                "2026-09-04"
            ]
        ),
    )

    return MarketDataResult(
        ticker=ticker,
        data=data,
        provider="batch-test",
        retrieved_at_utc=datetime(
            2026,
            9,
            4,
            21,
            0,
            tzinfo=timezone.utc,
        ),
    )


def make_quality_report(
    result: MarketDataResult,
) -> DataQualityReport:

    return DataQualityReport(
        ticker=result.ticker,
        checked_at_utc=datetime(
            2026,
            9,
            4,
            21,
            1,
            tzinfo=timezone.utc,
        ),
        latest_data_session=date(
            2026,
            9,
            4,
        ),
        latest_expected_completed_session=date(
            2026,
            9,
            4,
        ),
        issues=(),
    )


class FakeDecisionOrchestrator:

    def __init__(
        self,
    ):

        self.calls = []

    def run(
        self,
        **kwargs,
    ):

        self.calls.append(
            kwargs
        )

        ticker = (
            kwargs[
                "market_result"
            ].ticker
        )

        order_created = (
            ticker
            == "AAPL"
        )

        return SimpleNamespace(
            order_created=(
                order_created
            ),
            decision=(
                SimpleNamespace(
                    status=(
                        "BUY_APPROVED"
                        if order_created
                        else "NO_TRADE"
                    )
                )
            ),
        )


def decision_timestamp():

    return datetime(
        2026,
        9,
        4,
        21,
        0,
        tzinfo=timezone.utc,
    )


def test_batch_runs_all_tickers():

    orchestrator = (
        FakeDecisionOrchestrator()
    )

    runner = DailyBatchRunner(
        tickers=[
            "AAPL",
            "MSFT",
            "NVDA",
        ],
        market_data_fetcher=(
            make_market_result
        ),
        quality_report_builder=(
            make_quality_report
        ),
        decision_orchestrator=(
            orchestrator
        ),
    )

    result = runner.run(
        decision_timestamp=(
            decision_timestamp()
        )
    )

    assert (
        result.total_tickers
        == 3
    )

    assert (
        result.successful_tickers
        == 3
    )

    assert (
        result.failed_tickers
        == 0
    )

    assert (
        len(
            orchestrator.calls
        )
        == 3
    )


def test_one_ticker_failure_does_not_stop_batch():

    orchestrator = (
        FakeDecisionOrchestrator()
    )

    def fetcher(
        ticker,
    ):

        if ticker == "MSFT":
            raise RuntimeError(
                "Provider failure."
            )

        return make_market_result(
            ticker
        )

    runner = DailyBatchRunner(
        tickers=[
            "AAPL",
            "MSFT",
            "NVDA",
        ],
        market_data_fetcher=fetcher,
        quality_report_builder=(
            make_quality_report
        ),
        decision_orchestrator=(
            orchestrator
        ),
    )

    result = runner.run(
        decision_timestamp=(
            decision_timestamp()
        )
    )

    assert (
        result.total_tickers
        == 3
    )

    assert (
        result.successful_tickers
        == 2
    )

    assert (
        result.failed_tickers
        == 1
    )

    assert (
        result.failures[0].ticker
        == "MSFT"
    )

    assert (
        result.failures[0]
        .error_type
        == "RuntimeError"
    )

    # AAPL and NVDA still ran.
    assert (
        len(
            orchestrator.calls
        )
        == 2
    )


def test_order_count_is_reported():

    orchestrator = (
        FakeDecisionOrchestrator()
    )

    runner = DailyBatchRunner(
        tickers=[
            "AAPL",
            "MSFT",
        ],
        market_data_fetcher=(
            make_market_result
        ),
        quality_report_builder=(
            make_quality_report
        ),
        decision_orchestrator=(
            orchestrator
        ),
    )

    result = runner.run(
        decision_timestamp=(
            decision_timestamp()
        )
    )

    # Fake orchestrator creates an order
    # only for AAPL.
    assert (
        result.orders_created
        == 1
    )


def test_duplicate_tickers_are_removed():

    orchestrator = (
        FakeDecisionOrchestrator()
    )

    runner = DailyBatchRunner(
        tickers=[
            "aapl",
            "AAPL",
            " msft ",
            "MSFT",
        ],
        market_data_fetcher=(
            make_market_result
        ),
        quality_report_builder=(
            make_quality_report
        ),
        decision_orchestrator=(
            orchestrator
        ),
    )

    assert (
        runner.tickers
        == (
            "AAPL",
            "MSFT",
        )
    )


def test_empty_universe_is_rejected():

    with pytest.raises(
        InvalidTickerUniverseError
    ):
        DailyBatchRunner(
            tickers=[],
            market_data_fetcher=(
                make_market_result
            ),
            quality_report_builder=(
                make_quality_report
            ),
            decision_orchestrator=(
                FakeDecisionOrchestrator()
            ),
        )


def test_blank_ticker_is_rejected():

    with pytest.raises(
        InvalidTickerUniverseError
    ):
        DailyBatchRunner(
            tickers=[
                "AAPL",
                "   ",
            ],
            market_data_fetcher=(
                make_market_result
            ),
            quality_report_builder=(
                make_quality_report
            ),
            decision_orchestrator=(
                FakeDecisionOrchestrator()
            ),
        )


def test_wrong_provider_ticker_fails_only_that_ticker():

    orchestrator = (
        FakeDecisionOrchestrator()
    )

    def fetcher(
        ticker,
    ):

        if ticker == "AAPL":
            return make_market_result(
                "MSFT"
            )

        return make_market_result(
            ticker
        )

    runner = DailyBatchRunner(
        tickers=[
            "AAPL",
            "NVDA",
        ],
        market_data_fetcher=fetcher,
        quality_report_builder=(
            make_quality_report
        ),
        decision_orchestrator=(
            orchestrator
        ),
    )

    result = runner.run(
        decision_timestamp=(
            decision_timestamp()
        )
    )

    assert (
        result.successful_tickers
        == 1
    )

    assert (
        result.failed_tickers
        == 1
    )

    assert (
        result.failures[0]
        .error_type
        == "DailyBatchRunnerError"
    )


def test_wrong_quality_report_ticker_fails():

    orchestrator = (
        FakeDecisionOrchestrator()
    )

    def bad_quality_builder(
        result,
    ):

        report = (
            make_quality_report(
                result
            )
        )

        return DataQualityReport(
            ticker="WRONG",
            checked_at_utc=(
                report.checked_at_utc
            ),
            latest_data_session=(
                report.latest_data_session
            ),
            latest_expected_completed_session=(
                report
                .latest_expected_completed_session
            ),
            issues=report.issues,
        )

    runner = DailyBatchRunner(
        tickers=[
            "AAPL",
        ],
        market_data_fetcher=(
            make_market_result
        ),
        quality_report_builder=(
            bad_quality_builder
        ),
        decision_orchestrator=(
            orchestrator
        ),
    )

    result = runner.run(
        decision_timestamp=(
            decision_timestamp()
        )
    )

    assert (
        result.failed_tickers
        == 1
    )

    assert (
        len(
            orchestrator.calls
        )
        == 0
    )


def test_market_prices_are_forwarded():

    orchestrator = (
        FakeDecisionOrchestrator()
    )

    runner = DailyBatchRunner(
        tickers=[
            "AAPL",
        ],
        market_data_fetcher=(
            make_market_result
        ),
        quality_report_builder=(
            make_quality_report
        ),
        decision_orchestrator=(
            orchestrator
        ),
    )

    prices = {
        "AAPL": 100,
        "MSFT": 200,
    }

    runner.run(
        decision_timestamp=(
            decision_timestamp()
        ),
        market_prices=prices,
    )

    call = (
        orchestrator.calls[0]
    )

    assert (
        call[
            "decision_kwargs"
        ][
            "market_prices"
        ]
        == prices
    )


def test_order_id_factory_is_used():

    orchestrator = (
        FakeDecisionOrchestrator()
    )

    runner = DailyBatchRunner(
        tickers=[
            "AAPL",
            "MSFT",
        ],
        market_data_fetcher=(
            make_market_result
        ),
        quality_report_builder=(
            make_quality_report
        ),
        decision_orchestrator=(
            orchestrator
        ),
    )

    runner.run(
        decision_timestamp=(
            decision_timestamp()
        ),
        order_id_factory=(
            lambda ticker:
            f"20260904-{ticker}"
        ),
    )

    assert (
        orchestrator.calls[0][
            "order_id"
        ]
        == "20260904-AAPL"
    )

    assert (
        orchestrator.calls[1][
            "order_id"
        ]
        == "20260904-MSFT"
    )