
from datetime import date, datetime, timedelta, timezone

import pytest

from services.intraday_collector import IntradayObservation
from trading.flexible_execution_observation import (
    FlexibleExecutionObservationError,
    FlexibleExecutionObservationValidator,
)


UTC = timezone.utc
SESSION = date(2026, 9, 16)

BAR_START = datetime(
    2026, 9, 16, 14, 0,
    tzinfo=UTC,
)

RETRIEVED = datetime(
    2026, 9, 16, 14, 1, 10,
    tzinfo=UTC,
)

CHECKED = datetime(
    2026, 9, 16, 14, 2,
    tzinfo=UTC,
)


def make_observation(**changes):
    values = {
        "ticker": "AAPL",
        "provider": "yfinance-1m-observation",
        "bar_start_utc": BAR_START,
        "retrieved_at_utc": RETRIEVED,
        "open": 100.0,
        "high": 102.0,
        "low": 99.0,
        "close": 101.0,
        "volume": 1000.0,
    }

    values.update(changes)

    return IntradayObservation(**values)


def validate(observation=None, **changes):
    if observation is None:
        observation = make_observation()

    return FlexibleExecutionObservationValidator().validate(
        observation=observation,
        execution_session=changes.get(
            "execution_session", SESSION
        ),
        checked_at=changes.get(
            "checked_at", CHECKED
        ),
        expected_ticker=changes.get(
            "expected_ticker", "AAPL"
        ),
    )


def test_valid_observation_uses_close():
    result = validate()

    assert result.reference_price == 101.0
    assert result.price_field == "Close"
    assert result.model == "flexible-observed-close-v1"


def test_before_window_rejected():
    with pytest.raises(
        FlexibleExecutionObservationError
    ):
        validate(
            checked_at=datetime(
                2026, 9, 16, 13, 40,
                tzinfo=UTC,
            )
        )


def test_after_window_rejected():
    with pytest.raises(
        FlexibleExecutionObservationError
    ):
        validate(
            checked_at=datetime(
                2026, 9, 16, 14, 31,
                tzinfo=UTC,
            )
        )


def test_future_retrieval_rejected():
    with pytest.raises(
        FlexibleExecutionObservationError
    ):
        validate(
            make_observation(
                retrieved_at_utc=(
                    CHECKED + timedelta(seconds=1)
                )
            )
        )


def test_incomplete_bar_rejected():
    with pytest.raises(
        FlexibleExecutionObservationError
    ):
        validate(
            make_observation(
                retrieved_at_utc=(
                    BAR_START + timedelta(seconds=30)
                )
            )
        )


def test_stale_observation_rejected():
    with pytest.raises(
        FlexibleExecutionObservationError
    ):
        validate(
            checked_at=(
                BAR_START + timedelta(minutes=10)
            )
        )


def test_wrong_ticker_rejected():
    with pytest.raises(
        FlexibleExecutionObservationError
    ):
        validate(
            expected_ticker="MSFT"
        )


def test_weekend_rejected():
    with pytest.raises(
        FlexibleExecutionObservationError
    ):
        validate(
            execution_session=date(
                2026, 9, 19
            )
        )


def test_negative_close_rejected():
    with pytest.raises(
        FlexibleExecutionObservationError
    ):
        validate(
            make_observation(close=-1.0)
        )


def test_naive_timestamp_rejected():
    with pytest.raises(
        FlexibleExecutionObservationError
    ):
        validate(
            checked_at=datetime(
                2026, 9, 16, 14, 2
            )
        )