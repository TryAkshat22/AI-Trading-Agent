from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

import pandas as pd
import yfinance as yf


class MarketDataError(Exception):
    """Base exception for market-data failures."""


class DataValidationError(MarketDataError):
    """Raised when retrieved market data fails validation."""


@dataclass(frozen=True)
class MarketDataResult:
    ticker: str
    data: pd.DataFrame
    provider: str
    retrieved_at_utc: datetime


class MarketDataProvider(Protocol):
    def get_daily_history(
        self,
        ticker: str,
        period: str = "1y",
    ) -> MarketDataResult:
        ...


class YahooFinanceProvider:
    """
    Version 1 market-data provider.

    yfinance is intentionally isolated inside this class so that
    another provider can replace it later without requiring changes
    throughout the rest of the application.
    """

    PROVIDER_NAME = "yfinance"

    def get_daily_history(
        self,
        ticker: str,
        period: str = "1y",
    ) -> MarketDataResult:

        ticker = ticker.strip().upper()

        if not ticker:
            raise ValueError("Ticker cannot be empty.")

        try:
            data = yf.download(
                ticker,
                period=period,
                interval="1d",

                # Preserve actual/raw trading prices.
                # Adjusted prices remain available separately
                # through the "Adj Close" column.
                auto_adjust=False,

                # Include dividends and stock splits so that
                # corporate actions can be handled explicitly.
                actions=True,

                # Allow yfinance to repair certain known data issues.
                repair=True,

                progress=False,
                multi_level_index=False,
                timeout=10,
            )

        except Exception as exc:
            raise MarketDataError(
                f"Failed to retrieve data for {ticker}: {exc}"
            ) from exc

        data = self._normalize(data)
        self._validate(ticker, data)

        return MarketDataResult(
            ticker=ticker,
            data=data,
            provider=self.PROVIDER_NAME,
            retrieved_at_utc=datetime.now(timezone.utc),
        )

    @staticmethod
    def _normalize(data: pd.DataFrame) -> pd.DataFrame:
        """
        Normalize provider output into the format expected by our system.

        We intentionally preserve:
        - Raw OHLC prices
        - Adjusted closing prices
        - Volume
        - Dividends
        - Stock splits
        - Repair flags, if supplied by the provider
        """

        if data is None:
            return pd.DataFrame()

        data = data.copy()

        # Convert the index into a consistent datetime representation.
        data.index = pd.to_datetime(data.index)

        # Ensure observations are always chronological.
        data = data.sort_index()

        wanted_columns = [
            "Open",
            "High",
            "Low",
            "Close",
            "Adj Close",
            "Volume",
            "Dividends",
            "Stock Splits",
            "Repaired?",
        ]

        available_columns = [
            column
            for column in wanted_columns
            if column in data.columns
        ]

        return data[available_columns]

    @staticmethod
    def _validate(
        ticker: str,
        data: pd.DataFrame,
    ) -> None:
        """
        Reject obviously unusable or structurally invalid market data.

        These checks intentionally focus on errors that should stop
        downstream trading logic completely.

        More nuanced checks such as stale data, missing NYSE sessions,
        unusual price movements, and provider repair warnings will be
        handled by the dedicated data-quality layer later.
        """

        if data.empty:
            raise DataValidationError(
                f"No market data returned for {ticker}."
            )

        required_columns = {
            "Open",
            "High",
            "Low",
            "Close",
            "Volume",
        }

        missing_columns = (
            required_columns - set(data.columns)
        )

        if missing_columns:
            raise DataValidationError(
                f"{ticker} is missing required columns: "
                f"{sorted(missing_columns)}"
            )

        # Duplicate trading dates can corrupt return calculations,
        # indicators, and simulated executions.
        if data.index.has_duplicates:
            raise DataValidationError(
                f"{ticker} contains duplicate timestamps."
            )

        # Market observations must be chronological.
        if not data.index.is_monotonic_increasing:
            raise DataValidationError(
                f"{ticker} timestamps are not sorted."
            )

        price_columns = [
            "Open",
            "High",
            "Low",
            "Close",
        ]

        # Missing core prices are not safe for trading.
        if data[price_columns].isna().any().any():
            raise DataValidationError(
                f"{ticker} contains missing OHLC prices."
            )

        # A valid listed equity should never have a zero or
        # negative raw trading price.
        if (data[price_columns] <= 0).any().any():
            raise DataValidationError(
                f"{ticker} contains zero or negative prices."
            )

        # Volume cannot logically be negative.
        if (data["Volume"].dropna() < 0).any():
            raise DataValidationError(
                f"{ticker} contains negative volume."
            )

        # Daily High must be at least as large as every other
        # daily trading price.
        invalid_high = (
            data["High"]
            < data[
                [
                    "Open",
                    "Close",
                    "Low",
                ]
            ].max(axis=1)
        )

        if invalid_high.any():
            raise DataValidationError(
                f"{ticker} contains invalid daily high values."
            )

        # Daily Low must be no greater than every other
        # daily trading price.
        invalid_low = (
            data["Low"]
            > data[
                [
                    "Open",
                    "Close",
                    "High",
                ]
            ].min(axis=1)
        )

        if invalid_low.any():
            raise DataValidationError(
                f"{ticker} contains invalid daily low values."
            )

        # Adjusted close is useful for historical-return analysis.
        # It is not required for simulated execution, but if supplied
        # by the provider it should still be usable.
        if "Adj Close" in data.columns:
            adjusted_close = data["Adj Close"].dropna()

            if (adjusted_close <= 0).any():
                raise DataValidationError(
                    f"{ticker} contains invalid adjusted close values."
                )


def get_market_data(
    ticker: str,
    period: str = "1y",
    provider: MarketDataProvider | None = None,
) -> MarketDataResult:
    """
    Public entry point for requesting market data.

    Other application modules should use this function instead
    of calling yfinance directly.

    That keeps the rest of the system independent of the
    underlying market-data provider.
    """

    if provider is None:
        provider = YahooFinanceProvider()

    return provider.get_daily_history(
        ticker=ticker,
        period=period,
    )