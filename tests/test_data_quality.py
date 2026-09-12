from datetime import datetime, timezone

import pandas as pd

from services.data_quality import (
    Severity,
    validate_market_data,
)
from services.market_data import MarketDataResult


def make_result(
    dates,
    repaired=None,
):
    row_count = len(dates)

    data = pd.DataFrame(
        {
            "Open": [100.0] * row_count,
            "High": [105.0] * row_count,
            "Low": [95.0] * row_count,
            "Close": [102.0] * row_count,
            "Adj Close": [102.0] * row_count,
            "Volume": [1_000_000] * row_count,
        },
        index=pd.to_datetime(dates),
    )

    if repaired is not None:
        data["Repaired?"] = repaired

    return MarketDataResult(
        ticker="TEST",
        data=data,
        provider="test",
        retrieved_at_utc=datetime(
            2026,
            9,
            4,
            22,
            0,
            tzinfo=timezone.utc,
        ),
    )


def test_valid_sessions_are_safe():

    result = make_result(
        [
            "2026-09-01",
            "2026-09-02",
            "2026-09-03",
            "2026-09-04",
        ]
    )

    report = validate_market_data(
        result,
        now_utc=datetime(
            2026,
            9,
            7,
            22,
            0,
            tzinfo=timezone.utc,
        ),
    )

    assert report.safe_to_use is True
    assert (
        report.latest_expected_completed_session
        .isoformat()
        == "2026-09-04"
    )


def test_missing_session_is_critical():

    result = make_result(
        [
            "2026-09-01",
            "2026-09-02",
            # September 3 deliberately missing
            "2026-09-04",
        ]
    )

    report = validate_market_data(
        result,
        now_utc=datetime(
            2026,
            9,
            7,
            22,
            0,
            tzinfo=timezone.utc,
        ),
    )

    assert report.safe_to_use is False

    codes = {
        issue.code
        for issue in report.issues
    }

    assert "MISSING_TRADING_SESSIONS" in codes


def test_weekend_row_is_rejected():

    result = make_result(
        [
            "2026-09-03",
            "2026-09-04",
            "2026-09-05",
        ]
    )

    report = validate_market_data(
        result,
        now_utc=datetime(
            2026,
            9,
            7,
            22,
            0,
            tzinfo=timezone.utc,
        ),
    )

    assert report.safe_to_use is False

    codes = {
        issue.code
        for issue in report.issues
    }

    assert "UNEXPECTED_TRADING_SESSIONS" in codes


def test_stale_data_is_rejected():

    result = make_result(
        [
            "2026-09-01",
            "2026-09-02",
            "2026-09-03",
        ]
    )

    report = validate_market_data(
        result,
        now_utc=datetime(
            2026,
            9,
            7,
            22,
            0,
            tzinfo=timezone.utc,
        ),
    )

    assert report.safe_to_use is False

    codes = {
        issue.code
        for issue in report.issues
    }

    assert "STALE_DATA" in codes


def test_repaired_rows_create_warning():

    result = make_result(
        [
            "2026-09-03",
            "2026-09-04",
        ],
        repaired=[
            False,
            True,
        ],
    )

    report = validate_market_data(
        result,
        now_utc=datetime(
            2026,
            9,
            7,
            22,
            0,
            tzinfo=timezone.utc,
        ),
    )

    warnings = [
        issue
        for issue in report.issues
        if issue.severity == Severity.WARNING
    ]

    codes = {
        issue.code
        for issue in warnings
    }

    assert "PROVIDER_REPAIRS" in codes