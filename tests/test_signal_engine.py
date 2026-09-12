from datetime import datetime, timezone
from decimal import Decimal

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
from signals.signal_engine import (
    SignalAction,
    SignalConfig,
    SignalEngine,
    SignalReason,
    UnsafeSignalDataError,
)


def make_result(
    closes,
    extra_future_close=None,
    adjusted_closes=None,
):

    dates = pd.bdate_range(
        start="2026-05-01",
        periods=len(closes),
    )

    if adjusted_closes is None:
        adjusted_closes = closes

    if len(adjusted_closes) != len(closes):
        raise ValueError(
            "adjusted_closes must have the "
            "same length as closes."
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
            "Adj Close": adjusted_closes,
            "Volume": [
                1_000_000
                for _ in closes
            ],
        },
        index=dates,
    )

    if extra_future_close is not None:

        future_date = (
            dates[-1]
            + pd.Timedelta(days=1)
        )

        data.loc[
            future_date
        ] = {
            "Open": extra_future_close,
            "High": (
                extra_future_close + 1
            ),
            "Low": (
                extra_future_close - 1
            ),
            "Close": extra_future_close,
            "Adj Close": extra_future_close,
            "Volume": 1_000_000,
        }

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
    safe=True,
):

    latest_session = (
        result.data.index[-1].date()
    )

    issues = ()

    if not safe:
        issues = (
            DataQualityIssue(
                severity=Severity.CRITICAL,
                code="TEST_FAILURE",
                message="Unsafe test data.",
            ),
        )

    return DataQualityReport(
        ticker="AAPL",
        checked_at_utc=datetime(
            2026,
            9,
            9,
            tzinfo=timezone.utc,
        ),
        latest_data_session=latest_session,
        latest_expected_completed_session=(
            latest_session
        ),
        issues=issues,
    )


def test_bullish_signal_generates_buy():

    closes = list(
        range(100, 180)
    )

    result = make_result(
        closes
    )

    report = make_report(
        result
    )

    signal = SignalEngine().generate(
        market_result=result,
        quality_report=report,
        has_position=False,
    )

    assert signal.action == SignalAction.BUY
    assert signal.actionable is True
    assert signal.reason == (
        SignalReason.BULLISH_TREND
    )


def test_existing_position_generates_hold():

    closes = list(
        range(100, 180)
    )

    result = make_result(
        closes
    )

    signal = SignalEngine().generate(
        market_result=result,
        quality_report=make_report(result),
        has_position=True,
    )

    assert signal.action == SignalAction.HOLD
    assert signal.actionable is False


def test_downtrend_generates_no_trade():

    closes = list(
        range(200, 120, -1)
    )

    result = make_result(
        closes
    )

    signal = SignalEngine().generate(
        result,
        make_report(result),
    )

    assert signal.action == SignalAction.NO_TRADE

    assert signal.reason == (
        SignalReason.TREND_FILTER_FAILED
    )


def test_insufficient_history_returns_no_trade():

    closes = list(
        range(100, 130)
    )

    result = make_result(
        closes
    )

    signal = SignalEngine().generate(
        result,
        make_report(result),
    )

    assert signal.action == SignalAction.NO_TRADE

    assert signal.reason == (
        SignalReason.INSUFFICIENT_HISTORY
    )


def test_unsafe_data_is_rejected():

    result = make_result(
        list(range(100, 180))
    )

    with pytest.raises(
        UnsafeSignalDataError
    ):
        SignalEngine().generate(
            result,
            make_report(
                result,
                safe=False,
            ),
        )


def test_future_incomplete_bar_is_ignored():

    closes = list(
        range(100, 180)
    )

    result = make_result(
        closes,
        extra_future_close=1,
    )

    completed_session = (
        result.data.index[-2].date()
    )

    report = DataQualityReport(
        ticker="AAPL",
        checked_at_utc=datetime(
            2026,
            9,
            9,
            tzinfo=timezone.utc,
        ),
        latest_data_session=(
            result.data.index[-1].date()
        ),
        latest_expected_completed_session=(
            completed_session
        ),
        issues=(),
    )

    signal = SignalEngine().generate(
        result,
        report,
    )

    assert signal.action == SignalAction.BUY

    assert signal.source_session == (
        completed_session
    )

    assert signal.close != 1


def test_ticker_mismatch_is_rejected():

    result = make_result(
        list(range(100, 180))
    )

    report = DataQualityReport(
        ticker="MSFT",
        checked_at_utc=datetime(
            2026,
            9,
            9,
            tzinfo=timezone.utc,
        ),
        latest_data_session=(
            result.data.index[-1].date()
        ),
        latest_expected_completed_session=(
            result.data.index[-1].date()
        ),
        issues=(),
    )

    with pytest.raises(
        Exception
    ):
        SignalEngine().generate(
            result,
            report,
        )


def test_missing_close_is_rejected():

    result = make_result(
        list(range(100, 180))
    )

    result.data.drop(
        columns=["Close"],
        inplace=True,
    )

    with pytest.raises(
        UnsafeSignalDataError
    ):
        SignalEngine().generate(
            result,
            make_report(result),
        )


def test_invalid_sma_config_is_rejected():

    with pytest.raises(
        ValueError
    ):
        SignalEngine(
            SignalConfig(
                sma_window=1,
            )
        )


def test_invalid_momentum_config_is_rejected():

    with pytest.raises(
        ValueError
    ):
        SignalEngine(
            SignalConfig(
                momentum_window=0,
            )
        )


def test_existing_position_exits_when_trend_fails():

    closes = list(
        range(200, 120, -1)
    )

    result = make_result(
        closes
    )

    signal = SignalEngine().generate(
        market_result=result,
        quality_report=make_report(result),
        has_position=True,
    )

    assert signal.action == SignalAction.EXIT

    assert signal.reason == (
        SignalReason.EXIT_TREND_FAILED
    )

    assert signal.actionable is True


def test_existing_bullish_position_holds():

    closes = list(
        range(100, 180)
    )

    result = make_result(
        closes
    )

    signal = SignalEngine().generate(
        market_result=result,
        quality_report=make_report(result),
        has_position=True,
    )

    assert signal.action == SignalAction.HOLD

    assert signal.reason == (
        SignalReason.EXISTING_BULLISH_POSITION
    )


def test_missing_expected_completed_session_is_rejected():

    result = make_result(
        list(range(100, 180))
    )

    actual_latest = (
        result.data.index[-1].date()
    )

    false_expected_session = (
        result.data.index[-1]
        + pd.Timedelta(days=1)
    ).date()

    report = DataQualityReport(
        ticker="AAPL",
        checked_at_utc=datetime(
            2026,
            9,
            9,
            tzinfo=timezone.utc,
        ),
        latest_data_session=actual_latest,
        latest_expected_completed_session=(
            false_expected_session
        ),
        issues=(),
    )

    with pytest.raises(
        UnsafeSignalDataError
    ):
        SignalEngine().generate(
            result,
            report,
        )


def test_stock_split_does_not_create_false_exit():

    # Economic value keeps trending upward.
    #
    # Adjusted series correctly represents
    # the continuous historical trend.
    adjusted_closes = list(
        range(100, 180)
    )

    # Simulate a 2-for-1 split in the raw series.
    #
    # The last 10 raw prices suddenly appear
    # roughly 50% lower even though the economic
    # trend has not collapsed.
    raw_closes = (
        list(range(100, 170))
        + [
            value / 2
            for value in range(
                170,
                180,
            )
        ]
    )

    result = make_result(
        closes=raw_closes,
        adjusted_closes=adjusted_closes,
    )

    signal = SignalEngine().generate(
        market_result=result,
        quality_report=make_report(
            result
        ),
        has_position=True,
    )

    # If indicators incorrectly used raw Close,
    # this synthetic split could appear bearish.
    #
    # Using Adj Close should preserve the
    # underlying bullish trend.
    assert (
        signal.action
        == SignalAction.HOLD
    )

    assert (
        signal.reason
        == SignalReason
        .EXISTING_BULLISH_POSITION
    )


def test_missing_adjusted_close_is_rejected():

    result = make_result(
        list(range(100, 180))
    )

    result.data.drop(
        columns=[
            "Adj Close"
        ],
        inplace=True,
    )

    with pytest.raises(
        UnsafeSignalDataError
    ):
        SignalEngine().generate(
            market_result=result,
            quality_report=(
                make_report(result)
            ),
        )


def test_signal_reference_close_remains_raw():

    adjusted_closes = list(
        range(100, 180)
    )

    raw_closes = (
        list(range(100, 170))
        + [
            value / 2
            for value in range(
                170,
                180,
            )
        ]
    )

    result = make_result(
        closes=raw_closes,
        adjusted_closes=adjusted_closes,
    )

    signal = SignalEngine().generate(
        market_result=result,
        quality_report=make_report(
            result
        ),
        has_position=False,
    )

    assert (
        signal.action
        == SignalAction.BUY
    )

    # Raw final Close:
    # 179 / 2 = 89.5
    assert signal.close == Decimal(
        "89.5"
    )

    # Indicators still see the adjusted bullish
    # historical series.
    assert signal.momentum > Decimal(
        "0"
    )