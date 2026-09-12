from datetime import datetime, timezone

import pandas as pd
import pytest

from database.storage import (
    MarketDataStorage,
    UnsafeDataError,
)
from services.data_quality import (
    DataQualityReport,
    DataQualityIssue,
    Severity,
)
from services.market_data import (
    MarketDataResult,
)


def make_market_result():

    data = pd.DataFrame(
        {
            "Open": [100.0, 102.0],
            "High": [105.0, 106.0],
            "Low": [98.0, 101.0],
            "Close": [103.0, 105.0],
            "Adj Close": [103.0, 105.0],
            "Volume": [
                1_000_000,
                1_200_000,
            ],
            "Dividends": [
                0.0,
                0.0,
            ],
            "Stock Splits": [
                0.0,
                0.0,
            ],
            "Repaired?": [
                False,
                False,
            ],
        },
        index=pd.to_datetime(
            [
                "2026-09-03",
                "2026-09-04",
            ]
        ),
    )

    return MarketDataResult(
        ticker="TEST",
        data=data,
        provider="test_provider",
        retrieved_at_utc=datetime(
            2026,
            9,
            4,
            22,
            0,
            tzinfo=timezone.utc,
        ),
    )


def make_safe_report():

    return DataQualityReport(
        ticker="TEST",
        checked_at_utc=datetime(
            2026,
            9,
            4,
            22,
            1,
            tzinfo=timezone.utc,
        ),
        latest_data_session=pd.Timestamp(
            "2026-09-04"
        ).date(),
        latest_expected_completed_session=(
            pd.Timestamp(
                "2026-09-04"
            ).date()
        ),
        issues=(
            DataQualityIssue(
                severity=Severity.INFO,
                code="DATA_OK",
                message="Test data is valid.",
            ),
        ),
    )


def test_database_initialization(
    tmp_path,
):

    database_path = (
        tmp_path / "test.db"
    )

    storage = MarketDataStorage(
        database_path
    )

    storage.initialize()

    assert database_path.exists()


def test_market_snapshot_saves(
    tmp_path,
):

    database_path = (
        tmp_path / "test.db"
    )

    storage = MarketDataStorage(
        database_path
    )

    storage.initialize()

    result = storage.save_market_snapshot(
        result=make_market_result(),
        quality_report=make_safe_report(),
    )

    assert result.rows_saved == 2

    assert (
        storage.count_ingestion_runs()
        == 1
    )

    assert (
        storage.count_market_bars()
        == 2
    )


def test_multiple_snapshots_are_preserved(
    tmp_path,
):

    storage = MarketDataStorage(
        tmp_path / "test.db"
    )

    storage.initialize()

    market_result = (
        make_market_result()
    )

    quality_report = (
        make_safe_report()
    )

    first = storage.save_market_snapshot(
        market_result,
        quality_report,
    )

    second = storage.save_market_snapshot(
        market_result,
        quality_report,
    )

    assert (
        first.run_id
        != second.run_id
    )

    assert (
        storage.count_ingestion_runs()
        == 2
    )

    assert (
        storage.count_market_bars()
        == 4
    )


def test_unsafe_data_is_not_saved(
    tmp_path,
):

    storage = MarketDataStorage(
        tmp_path / "test.db"
    )

    storage.initialize()

    unsafe_report = DataQualityReport(
        ticker="TEST",
        checked_at_utc=datetime(
            2026,
            9,
            4,
            22,
            0,
            tzinfo=timezone.utc,
        ),
        latest_data_session=pd.Timestamp(
            "2026-09-03"
        ).date(),
        latest_expected_completed_session=(
            pd.Timestamp(
                "2026-09-04"
            ).date()
        ),
        issues=(
            DataQualityIssue(
                severity=Severity.CRITICAL,
                code="STALE_DATA",
                message="Data is stale.",
            ),
        ),
    )

    with pytest.raises(
        UnsafeDataError
    ):
        storage.save_market_snapshot(
            result=make_market_result(),
            quality_report=unsafe_report,
        )

    assert (
        storage.count_ingestion_runs()
        == 0
    )

    assert (
        storage.count_market_bars()
        == 0
    )