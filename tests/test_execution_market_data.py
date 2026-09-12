from __future__ import annotations

from datetime import (
    date,
    datetime,
    timezone,
)
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from services.execution_market_data import (
    DuplicateOpeningBarError,
    ExecutionDataTimezoneError,
    ExecutionRetrievalTimeError,
    InvalidExecutionSessionError,
    InvalidOpeningPriceError,
    OpeningBarMissingError,
    YahooNearOpenExecutionProvider,
)


SESSION = date(
    2026,
    9,
    14,
)

NEW_YORK = ZoneInfo(
    "America/New_York"
)


def make_intraday_data(
    *,
    opening_price: float = 100.0,
    opening_time: str = "09:30",
):

    index = pd.DatetimeIndex(
        [
            datetime(
                2026,
                9,
                14,
                int(
                    opening_time[
                        :2
                    ]
                ),
                int(
                    opening_time[
                        3:
                    ]
                ),
                tzinfo=(
                    NEW_YORK
                ),
            )
        ]
    )

    return pd.DataFrame(
        {
            "Open": [
                opening_price
            ],
            "High": [
                opening_price
                + 1
            ],
            "Low": [
                opening_price
                - 1
            ],
            "Close": [
                opening_price
                + 0.5
            ],
            "Adj Close": [
                opening_price
                + 0.5
            ],
            "Volume": [
                100_000
            ],
        },
        index=index,
    )


def valid_clock():

    return datetime(
        2026,
        9,
        14,
        13,
        31,
        tzinfo=timezone.utc,
    )


def make_provider(
    data=None,
    clock=valid_clock,
):

    if data is None:

        data = (
            make_intraday_data()
        )

    return (
        YahooNearOpenExecutionProvider(
            execution_session=(
                SESSION
            ),
            clock=clock,
            history_loader=(
                lambda ticker:
                data
            ),
        )
    )


def test_valid_opening_bar_is_normalized():

    provider = (
        make_provider()
    )

    result = (
        provider.get_market_data(
            "aapl"
        )
    )

    assert (
        result.ticker
        == "AAPL"
    )

    assert (
        result.provider
        == "yfinance-1m-open"
    )

    assert (
        len(
            result.data
        )
        == 1
    )

    assert (
        result.data.index[
            0
        ].date()
        == SESSION
    )

    assert (
        result.data[
            "Open"
        ].iloc[0]
        == 100.0
    )


def test_retrieval_before_open_is_rejected():

    def early_clock():

        return datetime(
            2026,
            9,
            14,
            13,
            29,
            59,
            tzinfo=timezone.utc,
        )

    provider = make_provider(
        clock=early_clock
    )

    with pytest.raises(
        ExecutionRetrievalTimeError
    ):

        provider.get_market_data(
            "AAPL"
        )


def test_retrieval_after_five_minutes_is_rejected():

    def late_clock():

        return datetime(
            2026,
            9,
            14,
            13,
            35,
            1,
            tzinfo=timezone.utc,
        )

    provider = make_provider(
        clock=late_clock
    )

    with pytest.raises(
        ExecutionRetrievalTimeError
    ):

        provider.get_market_data(
            "AAPL"
        )


def test_weekend_session_is_rejected():

    with pytest.raises(
        InvalidExecutionSessionError
    ):

        YahooNearOpenExecutionProvider(
            execution_session=date(
                2026,
                9,
                12,
            ),
            history_loader=(
                lambda ticker:
                make_intraday_data()
            ),
        )


def test_missing_exact_opening_bar_is_rejected():

    data = make_intraday_data(
        opening_time="09:31"
    )

    provider = make_provider(
        data=data
    )

    with pytest.raises(
        OpeningBarMissingError
    ):

        provider.get_market_data(
            "AAPL"
        )


def test_duplicate_opening_bar_is_rejected():

    first = make_intraday_data()

    duplicate = pd.concat(
        [
            first,
            first,
        ]
    )

    provider = make_provider(
        data=duplicate
    )

    with pytest.raises(
        DuplicateOpeningBarError
    ):

        provider.get_market_data(
            "AAPL"
        )


def test_nonpositive_open_is_rejected():

    data = make_intraday_data(
        opening_price=0
    )

    provider = make_provider(
        data=data
    )

    with pytest.raises(
        InvalidOpeningPriceError
    ):

        provider.get_market_data(
            "AAPL"
        )


def test_naive_intraday_index_is_rejected():

    data = (
        make_intraday_data()
        .copy()
    )

    data.index = (
        data.index
        .tz_localize(
            None
        )
    )

    provider = make_provider(
        data=data
    )

    with pytest.raises(
        ExecutionDataTimezoneError
    ):

        provider.get_market_data(
            "AAPL"
        )


def test_quality_report_matches_execution_session():

    provider = (
        make_provider()
    )

    result = (
        provider.get_market_data(
            "AAPL"
        )
    )

    report = (
        provider
        .build_quality_report(
            result
        )
    )

    assert (
        report.ticker
        == "AAPL"
    )

    assert (
        report.latest_data_session
        == SESSION
    )

    assert (
        report.latest_expected_completed_session
        == SESSION
    )

    assert (
        report.safe_to_use
        is True
    )


def test_observation_time_equals_retrieval_time():

    provider = (
        make_provider()
    )

    result = (
        provider.get_market_data(
            "AAPL"
        )
    )

    observed = (
        provider.observation_time(
            result
        )
    )

    assert (
        observed
        == result.retrieved_at_utc
    )