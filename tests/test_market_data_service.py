import pandas as pd
import pytest

from services.market_data import (
    DataValidationError,
    YahooFinanceProvider,
    get_market_data,
)


def test_market_data_download():
    result = get_market_data(
        ticker="AAPL",
        period="1mo",
    )

    assert result.ticker == "AAPL"
    assert result.provider == "yfinance"
    assert not result.data.empty

    required = {
        "Open",
        "High",
        "Low",
        "Close",
        "Volume",
    }

    assert required.issubset(result.data.columns)


def test_prices_are_positive():
    result = get_market_data(
        ticker="MSFT",
        period="1mo",
    )

    price_columns = [
        "Open",
        "High",
        "Low",
        "Close",
    ]

    assert (
        result.data[price_columns] > 0
    ).all().all()


def test_timestamps_are_ordered():
    result = get_market_data(
        ticker="GOOGL",
        period="1mo",
    )

    assert result.data.index.is_monotonic_increasing


def test_bad_dataset_is_rejected():

    bad_data = pd.DataFrame(
        {
            "Open": [100],
            "High": [90],
            "Low": [80],
            "Close": [95],
            "Volume": [1000],
        },
        index=pd.to_datetime(["2026-01-01"]),
    )

    provider = YahooFinanceProvider()

    with pytest.raises(DataValidationError):
        provider._validate(
            "TEST",
            bad_data,
        )