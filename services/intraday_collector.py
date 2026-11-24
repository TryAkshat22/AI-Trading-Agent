
from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Sequence

import pandas as pd
import pandas_market_calendars as mcal
import yfinance as yf

from database.storage import get_default_database_path


class IntradayCollectionError(Exception):
    pass


@dataclass(frozen=True)
class IntradayObservation:
    ticker: str
    provider: str
    bar_start_utc: datetime
    retrieved_at_utc: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class CollectionOutcome:
    ticker: str
    saved: bool
    error: str | None


@dataclass(frozen=True)
class CollectionBatchResult:
    outcomes: tuple[CollectionOutcome, ...]

    @property
    def saved(self) -> int:
        return sum(item.saved for item in self.outcomes)

    @property
    def failed(self) -> int:
        return sum(
            item.error is not None
            for item in self.outcomes
        )


def utc_iso(value: datetime) -> str:
    if value.tzinfo is None:
        raise IntradayCollectionError(
            "Timestamp must be timezone-aware."
        )

    return value.astimezone(timezone.utc).isoformat()


class IntradayObservationStorage:
    """
    Stores intraday observations independently
    of orders, fills and portfolio state.
    """

    def __init__(
        self,
        database_path: str | Path | None = None,
    ) -> None:
        if database_path is None:
            database_path = get_default_database_path()

        self.database_path = Path(database_path)

    def _connect(self):
        self.database_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        connection = sqlite3.connect(
            self.database_path,
            timeout=15,
        )

        connection.execute("PRAGMA busy_timeout = 15000")

        return connection

    def initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS
                intraday_observations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticker TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    bar_start_utc TEXT NOT NULL,
                    retrieved_at_utc TEXT NOT NULL,
                    open_price REAL NOT NULL,
                    high_price REAL NOT NULL,
                    low_price REAL NOT NULL,
                    close_price REAL NOT NULL,
                    volume REAL NOT NULL,

                    UNIQUE (
                        ticker,
                        provider,
                        bar_start_utc
                    )
                )
                """
            )

    def save(
        self,
        observation: IntradayObservation,
    ) -> bool:
        """
        Returns True when a new observation is stored.

        Repeated retrievals of the same provider bar
        do not overwrite the original observation.
        """

        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO
                intraday_observations (
                    ticker,
                    provider,
                    bar_start_utc,
                    retrieved_at_utc,
                    open_price,
                    high_price,
                    low_price,
                    close_price,
                    volume
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    observation.ticker,
                    observation.provider,
                    utc_iso(
                        observation.bar_start_utc
                    ),
                    utc_iso(
                        observation.retrieved_at_utc
                    ),
                    observation.open,
                    observation.high,
                    observation.low,
                    observation.close,
                    observation.volume,
                ),
            )

            return cursor.rowcount == 1

    def count(self) -> int:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*)
                FROM intraday_observations
                """
            ).fetchone()

        return int(row[0])


class YahooIntradayCollector:
    """
    Collects the most recent completed,
    sufficiently fresh 1-minute bar.

    This is observation-only infrastructure.

    It does NOT:
      - create trading signals
      - create orders
      - execute orders
      - write fills
      - modify portfolios
    """

    PROVIDER = "yfinance-1m-observation"

    def __init__(
        self,
        storage: IntradayObservationStorage,
        calendar_name: str = "NYSE",
        max_bar_age: timedelta = timedelta(
            minutes=5
        ),
        clock: Callable[[], datetime] | None = None,
        history_loader: Callable[
            [str], pd.DataFrame
        ] | None = None,
    ) -> None:
        if max_bar_age <= timedelta(0):
            raise ValueError(
                "max_bar_age must be positive."
            )

        self.storage = storage
        self.calendar = mcal.get_calendar(
            calendar_name
        )
        self.max_bar_age = max_bar_age

        self.clock = (
            clock
            if clock is not None
            else lambda: datetime.now(
                timezone.utc
            )
        )

        self.history_loader = (
            history_loader
            if history_loader is not None
            else self._load_history
        )

    @staticmethod
    def _load_history(ticker: str) -> pd.DataFrame:
        return yf.Ticker(ticker).history(
            period="1d",
            interval="1m",
            prepost=False,
            actions=False,
            auto_adjust=False,
            repair=True,
            keepna=False,
            timeout=10,
            raise_errors=True,
        )

    @staticmethod
    def _normalize_time(
        value: datetime,
    ) -> datetime:
        if not isinstance(value, datetime):
            raise IntradayCollectionError(
                "Clock returned an invalid value."
            )

        if value.tzinfo is None:
            raise IntradayCollectionError(
                "Clock returned a naive timestamp."
            )

        return value.astimezone(timezone.utc)

    def _session_bounds(
        self,
        timestamp: datetime,
    ) -> tuple[datetime, datetime]:
        session = timestamp.date()

        schedule = self.calendar.schedule(
            start_date=session,
            end_date=session,
        )

        if schedule.empty:
            raise IntradayCollectionError(
                "No valid NYSE session is available."
            )

        market_open = pd.Timestamp(
            schedule.iloc[0]["market_open"]
        ).to_pydatetime().astimezone(
            timezone.utc
        )

        market_close = pd.Timestamp(
            schedule.iloc[0]["market_close"]
        ).to_pydatetime().astimezone(
            timezone.utc
        )

        return market_open, market_close

    def collect_one(
        self,
        ticker: str,
    ) -> bool:
        ticker = ticker.strip().upper()

        if not ticker:
            raise ValueError(
                "Ticker cannot be empty."
            )

        started_at = self._normalize_time(
            self.clock()
        )

        market_open, market_close = (
            self._session_bounds(started_at)
        )

        if not (
            market_open + timedelta(minutes=1)
            <= started_at
            < market_close
        ):
            raise IntradayCollectionError(
                "Collection is outside regular "
                "market hours."
            )

        data = self.history_loader(ticker)

        # Capture the retrieval timestamp AFTER
        # the provider request finishes.
        retrieved_at = self._normalize_time(
            self.clock()
        )

        if not (
            market_open + timedelta(minutes=1)
            <= retrieved_at
            < market_close
        ):
            raise IntradayCollectionError(
                "Collection completed outside "
                "regular market hours."
            )

        if data is None or data.empty:
            raise IntradayCollectionError(
                f"No intraday data for {ticker}."
            )

        index = pd.DatetimeIndex(data.index)

        if index.tz is None:
            raise IntradayCollectionError(
                "Intraday bar timestamps "
                "must be timezone-aware."
            )

        utc_index = index.tz_convert("UTC")

        if utc_index.has_duplicates:
            raise IntradayCollectionError(
                "Duplicate intraday bar timestamps."
            )

        required = {
            "Open",
            "High",
            "Low",
            "Close",
            "Volume",
        }

        if not required.issubset(data.columns):
            raise IntradayCollectionError(
                "Required OHLCV columns are missing."
            )

        # A 1-minute bar is only eligible after
        # its entire interval has completed.
        bar_end = utc_index + pd.Timedelta(
            minutes=1
        )

        eligible = (
            (utc_index >= pd.Timestamp(market_open))
            & (bar_end <= pd.Timestamp(retrieved_at))
            & (bar_end <= pd.Timestamp(market_close))
        )

        candidates = data.loc[eligible].copy()

        if candidates.empty:
            raise IntradayCollectionError(
                "No completed regular-session bar "
                "is available."
            )

        candidate_times = utc_index[eligible]

        latest_position = int(
            candidate_times.argmax()
        )

        bar_start = candidate_times[
            latest_position
        ].to_pydatetime()

        bar_end_time = (
            bar_start + timedelta(minutes=1)
        )

        if (
            retrieved_at - bar_end_time
            > self.max_bar_age
        ):
            raise IntradayCollectionError(
                "Most recent completed bar is stale."
            )

        row = candidates.iloc[
            latest_position
        ]

        try:
            prices = {
                column: float(row[column])
                for column in (
                    "Open",
                    "High",
                    "Low",
                    "Close",
                )
            }

            volume = float(row["Volume"])

        except (TypeError, ValueError) as exc:
            raise IntradayCollectionError(
                "Intraday OHLCV is not numeric."
            ) from exc

        if not all(
            math.isfinite(value) and value > 0
            for value in prices.values()
        ):
            raise IntradayCollectionError(
                "Intraday prices must be finite "
                "and positive."
            )

        if not (
            math.isfinite(volume)
            and volume >= 0
        ):
            raise IntradayCollectionError(
                "Intraday volume is invalid."
            )

        if (
            prices["High"]
            < max(
                prices["Open"],
                prices["Close"],
                prices["Low"],
            )
            or prices["Low"]
            > min(
                prices["Open"],
                prices["Close"],
                prices["High"],
            )
        ):
            raise IntradayCollectionError(
                "Intraday OHLC values "
                "are inconsistent."
            )

        observation = IntradayObservation(
            ticker=ticker,
            provider=self.PROVIDER,
            bar_start_utc=bar_start,
            retrieved_at_utc=retrieved_at,
            open=prices["Open"],
            high=prices["High"],
            low=prices["Low"],
            close=prices["Close"],
            volume=volume,
        )

        return self.storage.save(observation)

    def collect_batch(
        self,
        tickers: Sequence[str],
    ) -> CollectionBatchResult:
        outcomes = []

        for ticker in dict.fromkeys(
            item.strip().upper()
            for item in tickers
        ):
            if not ticker:
                continue

            try:
                saved = self.collect_one(ticker)

                outcomes.append(
                    CollectionOutcome(
                        ticker=ticker,
                        saved=saved,
                        error=None,
                    )
                )

            except Exception as exc:
                outcomes.append(
                    CollectionOutcome(
                        ticker=ticker,
                        saved=False,
                        error=(
                            f"{type(exc).__name__}: "
                            f"{exc}"
                        ),
                    )
                )

        return CollectionBatchResult(
            outcomes=tuple(outcomes)
        )