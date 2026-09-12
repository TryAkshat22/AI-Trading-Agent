from __future__ import annotations

from datetime import (
    date,
    datetime,
    timedelta,
    timezone,
)

import pandas as pd
import pytest

from services.market_data import (
    MarketDataResult,
)
from trading.execution_observation import (
    ExecutionObservationBeforeOpenError,
    ExecutionObservationTooLateError,
    ExecutionObservationValidator,
    ExecutionSessionDataMissingError,
    ExecutionTickerMismatchError,
    InvalidExecutionOpenError,
    InvalidExecutionSessionError,
    MarketDataRetrievedBeforeOpenError,
    NaiveExecutionObservationError,
    ObservationBeforeRetrievalError,
)


EXECUTION_SESSION = date(
    2026,
    9,
    8,
)

# September 8, 2026 is during EDT.
# Regular NYSE open:
#
#     09:30 America/New_York
#     13:30 UTC


def make_market_result(
    *,
    ticker: str = "AAPL",
    session: str = "2026-09-08",
    open_price: float = 100.0,
    retrieved_at: datetime | None = None,
) -> MarketDataResult:

    if retrieved_at is None:
        retrieved_at = datetime(
            2026,
            9,
            8,
            13,
            30,
            30,
            tzinfo=timezone.utc,
        )

    data = pd.DataFrame(
        {
            "Open": [
                open_price
            ],
            "High": [
                open_price + 2
            ],
            "Low": [
                max(
                    open_price - 2,
                    0.01,
                )
            ],
            "Close": [
                open_price + 1
            ],
            "Adj Close": [
                open_price + 1
            ],
            "Volume": [
                1_000_000
            ],
        },
        index=pd.to_datetime(
            [
                session
            ]
        ),
    )

    return MarketDataResult(
        ticker=ticker,
        data=data,
        provider=(
            "execution-observation-test"
        ),
        retrieved_at_utc=(
            retrieved_at
        ),
    )


def make_validator(
) -> ExecutionObservationValidator:

    return ExecutionObservationValidator(
        calendar_name="NYSE",
        max_execution_delay=timedelta(
            minutes=5
        ),
    )


def test_valid_near_open_observation_passes():

    validator = make_validator()

    result = validator.validate(
        market_result=(
            make_market_result()
        ),
        execution_session=(
            EXECUTION_SESSION
        ),
        execution_observed_at=datetime(
            2026,
            9,
            8,
            13,
            31,
            0,
            tzinfo=timezone.utc,
        ),
        expected_ticker="AAPL",
    )

    assert (
        result.execution_session
        == EXECUTION_SESSION
    )

    assert (
        result.ticker
        == "AAPL"
    )

    assert (
        result.raw_open
        == 100.0
    )

    assert (
        result.market_open_utc
        == datetime(
            2026,
            9,
            8,
            13,
            30,
            tzinfo=timezone.utc,
        )
    )

    assert (
        result.seconds_after_open
        == 60.0
    )


def test_observation_before_open_is_rejected():

    validator = make_validator()

    with pytest.raises(
        ExecutionObservationBeforeOpenError
    ):
        validator.validate(
            market_result=(
                make_market_result()
            ),
            execution_session=(
                EXECUTION_SESSION
            ),
            execution_observed_at=datetime(
                2026,
                9,
                8,
                13,
                29,
                59,
                tzinfo=timezone.utc,
            ),
            expected_ticker="AAPL",
        )


def test_observation_after_allowed_window_is_rejected():

    validator = make_validator()

    market_result = (
        make_market_result(
            retrieved_at=datetime(
                2026,
                9,
                8,
                13,
                30,
                30,
                tzinfo=timezone.utc,
            )
        )
    )

    with pytest.raises(
        ExecutionObservationTooLateError
    ):
        validator.validate(
            market_result=(
                market_result
            ),
            execution_session=(
                EXECUTION_SESSION
            ),
            execution_observed_at=datetime(
                2026,
                9,
                8,
                13,
                35,
                1,
                tzinfo=timezone.utc,
            ),
            expected_ticker="AAPL",
        )


def test_observation_before_retrieval_is_rejected():

    validator = make_validator()

    market_result = (
        make_market_result(
            retrieved_at=datetime(
                2026,
                9,
                8,
                13,
                32,
                0,
                tzinfo=timezone.utc,
            )
        )
    )

    with pytest.raises(
        ObservationBeforeRetrievalError
    ):
        validator.validate(
            market_result=(
                market_result
            ),
            execution_session=(
                EXECUTION_SESSION
            ),
            execution_observed_at=datetime(
                2026,
                9,
                8,
                13,
                31,
                0,
                tzinfo=timezone.utc,
            ),
            expected_ticker="AAPL",
        )


def test_market_data_retrieved_before_open_is_rejected():

    validator = make_validator()

    market_result = (
        make_market_result(
            retrieved_at=datetime(
                2026,
                9,
                8,
                13,
                29,
                59,
                tzinfo=timezone.utc,
            )
        )
    )

    with pytest.raises(
        MarketDataRetrievedBeforeOpenError
    ):
        validator.validate(
            market_result=(
                market_result
            ),
            execution_session=(
                EXECUTION_SESSION
            ),
            execution_observed_at=datetime(
                2026,
                9,
                8,
                13,
                31,
                0,
                tzinfo=timezone.utc,
            ),
            expected_ticker="AAPL",
        )


def test_wrong_execution_session_data_is_rejected():

    validator = make_validator()

    with pytest.raises(
        ExecutionSessionDataMissingError
    ):
        validator.validate(
            market_result=(
                make_market_result(
                    session=(
                        "2026-09-09"
                    )
                )
            ),
            execution_session=(
                EXECUTION_SESSION
            ),
            execution_observed_at=datetime(
                2026,
                9,
                8,
                13,
                31,
                0,
                tzinfo=timezone.utc,
            ),
            expected_ticker="AAPL",
        )


def test_weekend_execution_session_is_rejected():

    validator = make_validator()

    with pytest.raises(
        InvalidExecutionSessionError
    ):
        validator.validate(
            market_result=(
                make_market_result(
                    session=(
                        "2026-09-05"
                    ),
                    retrieved_at=datetime(
                        2026,
                        9,
                        5,
                        14,
                        0,
                        tzinfo=timezone.utc,
                    ),
                )
            ),
            execution_session=date(
                2026,
                9,
                5,
            ),
            execution_observed_at=datetime(
                2026,
                9,
                5,
                14,
                1,
                tzinfo=timezone.utc,
            ),
            expected_ticker="AAPL",
        )


def test_naive_execution_observation_is_rejected():

    validator = make_validator()

    with pytest.raises(
        NaiveExecutionObservationError
    ):
        validator.validate(
            market_result=(
                make_market_result()
            ),
            execution_session=(
                EXECUTION_SESSION
            ),
            execution_observed_at=datetime(
                2026,
                9,
                8,
                13,
                31,
                0,
            ),
            expected_ticker="AAPL",
        )


def test_nonpositive_raw_open_is_rejected():

    validator = make_validator()

    with pytest.raises(
        InvalidExecutionOpenError
    ):
        validator.validate(
            market_result=(
                make_market_result(
                    open_price=0.0
                )
            ),
            execution_session=(
                EXECUTION_SESSION
            ),
            execution_observed_at=datetime(
                2026,
                9,
                8,
                13,
                31,
                0,
                tzinfo=timezone.utc,
            ),
            expected_ticker="AAPL",
        )


def test_ticker_mismatch_is_rejected():

    validator = make_validator()

    with pytest.raises(
        ExecutionTickerMismatchError
    ):
        validator.validate(
            market_result=(
                make_market_result(
                    ticker="MSFT"
                )
            ),
            execution_session=(
                EXECUTION_SESSION
            ),
            execution_observed_at=datetime(
                2026,
                9,
                8,
                13,
                31,
                0,
                tzinfo=timezone.utc,
            ),
            expected_ticker="AAPL",
        )