from datetime import datetime, timezone

import pandas as pd
import pytest

from services.data_quality import (
    DataQualityIssue,
    DataQualityReport,
    Severity,
)
from services.market_data import (
    MarketDataResult,
)
from trading.execution_price import (
    InvalidExecutionPriceError,
    MissingExecutionSessionError,
    TickerMismatchError,
    UnsafeSnapshotError,
    resolve_execution_price,
)
from trading.execution_scheduler import (
    ExecutionScheduler,
)
from trading.portfolio import money


def make_market_result():

    data = pd.DataFrame(
        {
            "Open": [
                100.0,
                110.0,
            ],
            "High": [
                105.0,
                115.0,
            ],
            "Low": [
                95.0,
                108.0,
            ],
            "Close": [
                102.0,
                112.0,
            ],
            "Adj Close": [
                102.0,
                112.0,
            ],
            "Volume": [
                1_000_000,
                1_200_000,
            ],
        },
        index=pd.to_datetime(
            [
                "2026-09-04",
                "2026-09-08",
            ]
        ),
    )

    return MarketDataResult(
        ticker="AAPL",
        data=data,
        provider="test_provider",
        retrieved_at_utc=datetime(
            2026,
            9,
            8,
            20,
            0,
            tzinfo=timezone.utc,
        ),
    )


def make_safe_report():

    return DataQualityReport(
        ticker="AAPL",
        checked_at_utc=datetime(
            2026,
            9,
            8,
            20,
            1,
            tzinfo=timezone.utc,
        ),
        latest_data_session=pd.Timestamp(
            "2026-09-08"
        ).date(),
        latest_expected_completed_session=(
            pd.Timestamp(
                "2026-09-08"
            ).date()
        ),
        issues=(
            DataQualityIssue(
                severity=Severity.INFO,
                code="DATA_OK",
                message="Valid test data.",
            ),
        ),
    )


def make_execution_plan():

    scheduler = ExecutionScheduler()

    return scheduler.create_plan(
        datetime(
            2026,
            9,
            4,
            21,
            0,
            tzinfo=timezone.utc,
        )
    )


def test_execution_price_resolves_raw_open():

    result = resolve_execution_price(
        ticker="AAPL",
        execution_plan=make_execution_plan(),
        market_result=make_market_result(),
        quality_report=make_safe_report(),
        snapshot_id="run-123",
    )

    assert result.ticker == "AAPL"

    assert (
        result.execution_session.isoformat()
        == "2026-09-08"
    )

    assert result.raw_open == money(
        110.0
    )

    assert (
        result.snapshot_id
        == "run-123"
    )


def test_ticker_mismatch_is_rejected():

    with pytest.raises(
        TickerMismatchError
    ):
        resolve_execution_price(
            ticker="MSFT",
            execution_plan=make_execution_plan(),
            market_result=make_market_result(),
            quality_report=make_safe_report(),
        )


def test_unsafe_snapshot_is_rejected():

    unsafe_report = DataQualityReport(
        ticker="AAPL",
        checked_at_utc=datetime(
            2026,
            9,
            8,
            20,
            1,
            tzinfo=timezone.utc,
        ),
        latest_data_session=pd.Timestamp(
            "2026-09-04"
        ).date(),
        latest_expected_completed_session=(
            pd.Timestamp(
                "2026-09-08"
            ).date()
        ),
        issues=(
            DataQualityIssue(
                severity=Severity.CRITICAL,
                code="STALE_DATA",
                message="Test data is stale.",
            ),
        ),
    )

    with pytest.raises(
        UnsafeSnapshotError
    ):
        resolve_execution_price(
            ticker="AAPL",
            execution_plan=make_execution_plan(),
            market_result=make_market_result(),
            quality_report=unsafe_report,
        )


def test_missing_execution_session_is_rejected():

    data = pd.DataFrame(
        {
            "Open": [100.0],
            "High": [105.0],
            "Low": [95.0],
            "Close": [102.0],
            "Adj Close": [102.0],
            "Volume": [1_000_000],
        },
        index=pd.to_datetime(
            [
                "2026-09-04",
            ]
        ),
    )

    market_result = MarketDataResult(
        ticker="AAPL",
        data=data,
        provider="test_provider",
        retrieved_at_utc=datetime(
            2026,
            9,
            8,
            20,
            0,
            tzinfo=timezone.utc,
        ),
    )

    with pytest.raises(
        MissingExecutionSessionError
    ):
        resolve_execution_price(
            ticker="AAPL",
            execution_plan=make_execution_plan(),
            market_result=market_result,
            quality_report=make_safe_report(),
        )


def test_zero_open_price_is_rejected():

    result = make_market_result()

    bad_data = result.data.copy()

    bad_data.loc[
        pd.Timestamp("2026-09-08"),
        "Open",
    ] = 0

    bad_result = MarketDataResult(
        ticker=result.ticker,
        data=bad_data,
        provider=result.provider,
        retrieved_at_utc=result.retrieved_at_utc,
    )

    with pytest.raises(
        InvalidExecutionPriceError
    ):
        resolve_execution_price(
            ticker="AAPL",
            execution_plan=make_execution_plan(),
            market_result=bad_result,
            quality_report=make_safe_report(),
        )