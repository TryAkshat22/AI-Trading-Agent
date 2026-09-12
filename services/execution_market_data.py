from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Callable

import pandas as pd
import pandas_market_calendars as mcal
import yfinance as yf

from services.data_quality import (
    DataQualityReport,
)
from services.market_data import (
    MarketDataResult,
)


class ExecutionMarketDataError(Exception):
    """
    Base exception for near-open execution data.
    """


class InvalidExecutionSessionError(
    ExecutionMarketDataError
):
    """
    Requested date is not a valid NYSE session.
    """


class ExecutionRetrievalTimeError(
    ExecutionMarketDataError
):
    """
    Execution data was retrieved outside the
    allowed near-open window.
    """


class ExecutionDataEmptyError(
    ExecutionMarketDataError
):
    """
    Provider returned no intraday data.
    """


class ExecutionDataTimezoneError(
    ExecutionMarketDataError
):
    """
    Intraday timestamps are not timezone-aware.
    """


class OpeningBarMissingError(
    ExecutionMarketDataError
):
    """
    The exact official opening bar is absent.
    """


class DuplicateOpeningBarError(
    ExecutionMarketDataError
):
    """
    More than one bar represents the official open.
    """


class InvalidOpeningPriceError(
    ExecutionMarketDataError
):
    """
    Opening price is missing, invalid, or nonpositive.
    """


class YahooNearOpenExecutionProvider:
    """
    Fetches a time-authentic near-open observation
    from Yahoo Finance intraday data.

    The provider requests 1-minute regular-session
    bars and extracts ONLY the bar whose timestamp
    equals the official NYSE market open.

    That opening bar is normalized into the same
    one-row MarketDataResult shape already used by
    the execution stack.

    Important:

        This provider is execution-only.

        It is intentionally separate from the
        daily-history provider used for decisions.
    """

    def __init__(
        self,
        execution_session: date,
        calendar_name: str = "NYSE",
        max_execution_delay: timedelta = timedelta(
            minutes=5
        ),
        clock: Callable[
            [],
            datetime,
        ] | None = None,
        history_loader: Callable[
            [str],
            pd.DataFrame,
        ] | None = None,
    ) -> None:

        if not isinstance(
            execution_session,
            date,
        ):
            raise TypeError(
                "execution_session must be "
                "a datetime.date."
            )

        if max_execution_delay <= timedelta(0):
            raise ValueError(
                "max_execution_delay must be positive."
            )

        self.execution_session = (
            execution_session
        )

        self.calendar_name = (
            calendar_name
        )

        self.max_execution_delay = (
            max_execution_delay
        )

        self.clock = (
            clock
            if clock is not None
            else self._utc_now
        )

        self.history_loader = (
            history_loader
            if history_loader is not None
            else self._load_yahoo_history
        )

        self.calendar = mcal.get_calendar(
            calendar_name
        )

        self.market_open_utc = (
            self._resolve_market_open()
        )

    @staticmethod
    def _utc_now() -> datetime:

        return datetime.now(
            timezone.utc
        )

    def _resolve_market_open(
        self,
    ) -> datetime:

        schedule = self.calendar.schedule(
            start_date=(
                self.execution_session
            ),
            end_date=(
                self.execution_session
            ),
        )

        if schedule.empty:

            raise InvalidExecutionSessionError(
                f"{self.execution_session} is not "
                f"a valid {self.calendar_name} "
                "trading session."
            )

        market_open = (
            schedule.iloc[0][
                "market_open"
            ]
        )

        if hasattr(
            market_open,
            "to_pydatetime",
        ):
            market_open = (
                market_open
                .to_pydatetime()
            )

        if market_open.tzinfo is None:

            raise ExecutionMarketDataError(
                "Calendar returned a naive market "
                "open timestamp."
            )

        return market_open.astimezone(
            timezone.utc
        )

    def _load_yahoo_history(
        self,
        ticker: str,
    ) -> pd.DataFrame:

        yahoo_ticker = yf.Ticker(
            ticker
        )

        return yahoo_ticker.history(
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

    def _validate_retrieval_time(
        self,
        retrieved_at_utc: datetime,
    ) -> datetime:

        if retrieved_at_utc.tzinfo is None:

            raise ExecutionRetrievalTimeError(
                "Execution retrieval timestamp "
                "must be timezone-aware."
            )

        retrieved = (
            retrieved_at_utc
            .astimezone(
                timezone.utc
            )
        )

        latest_allowed = (
            self.market_open_utc
            + self.max_execution_delay
        )

        if retrieved < self.market_open_utc:

            raise ExecutionRetrievalTimeError(
                "Execution data was retrieved "
                "before the official market open."
            )

        if retrieved > latest_allowed:

            raise ExecutionRetrievalTimeError(
                "Execution data was retrieved "
                "after the allowed near-open "
                "execution window."
            )

        return retrieved

    def get_market_data(
        self,
        ticker: str,
    ) -> MarketDataResult:

        normalized_ticker = (
            ticker.strip().upper()
        )

        if not normalized_ticker:

            raise ValueError(
                "ticker cannot be blank."
            )

        # Capture retrieval time immediately before
        # the external provider request.
        retrieved_at_utc = (
            self._validate_retrieval_time(
                self.clock()
            )
        )

        raw = self.history_loader(
            normalized_ticker
        )

        if raw is None or raw.empty:

            raise ExecutionDataEmptyError(
                "Yahoo returned no intraday "
                f"data for {normalized_ticker}."
            )

        data = raw.copy()

        index = pd.DatetimeIndex(
            data.index
        )

        if index.tz is None:

            raise ExecutionDataTimezoneError(
                "Yahoo intraday timestamps must "
                "be timezone-aware."
            )

        utc_index = (
            index.tz_convert(
                "UTC"
            )
        )

        opening_mask = (
            utc_index
            == pd.Timestamp(
                self.market_open_utc
            )
        )

        opening_rows = data.loc[
            opening_mask
        ]

        if opening_rows.empty:

            raise OpeningBarMissingError(
                "The exact official opening "
                f"1-minute bar is missing for "
                f"{normalized_ticker} on "
                f"{self.execution_session}."
            )

        if len(opening_rows) != 1:

            raise DuplicateOpeningBarError(
                "Expected exactly one official "
                "opening bar."
            )

        row = opening_rows.iloc[0]

        if "Open" not in opening_rows.columns:

            raise InvalidOpeningPriceError(
                "Opening bar has no Open column."
            )

        try:

            raw_open = float(
                row[
                    "Open"
                ]
            )

        except (
            TypeError,
            ValueError,
        ) as exc:

            raise InvalidOpeningPriceError(
                "Opening price is not numeric."
            ) from exc

        if (
            pd.isna(
                raw_open
            )
            or raw_open <= 0
        ):

            raise InvalidOpeningPriceError(
                "Opening price must be positive."
            )

        normalized_row = {
            "Open": raw_open,
            "High": self._numeric_or_fallback(
                row,
                "High",
                raw_open,
            ),
            "Low": self._numeric_or_fallback(
                row,
                "Low",
                raw_open,
            ),
            "Close": self._numeric_or_fallback(
                row,
                "Close",
                raw_open,
            ),
            "Adj Close": self._numeric_or_fallback(
                row,
                "Adj Close",
                self._numeric_or_fallback(
                    row,
                    "Close",
                    raw_open,
                ),
            ),
            "Volume": self._numeric_or_fallback(
                row,
                "Volume",
                0,
            ),
        }

        normalized_data = pd.DataFrame(
            [
                normalized_row
            ],
            index=pd.to_datetime(
                [
                    self.execution_session
                    .isoformat()
                ]
            ),
        )

        return MarketDataResult(
            ticker=normalized_ticker,
            data=normalized_data,
            provider=(
                "yfinance-1m-open"
            ),
            retrieved_at_utc=(
                retrieved_at_utc
            ),
        )

    @staticmethod
    def _numeric_or_fallback(
        row,
        column: str,
        fallback,
    ):

        if column not in row.index:

            return fallback

        value = row[
            column
        ]

        if pd.isna(
            value
        ):
            return fallback

        try:
            return float(
                value
            )

        except (
            TypeError,
            ValueError,
        ):
            return fallback

    def build_quality_report(
        self,
        result: MarketDataResult,
    ) -> DataQualityReport:
        """
        Build the compatibility quality report used
        by the existing execution stack.

        Execution authenticity itself remains
        independently enforced by
        ExecutionObservationValidator.
        """

        if (
            result.ticker.strip().upper()
            != result.ticker
        ):
            raise ExecutionMarketDataError(
                "Execution result ticker must "
                "already be normalized."
            )

        if len(
            result.data
        ) != 1:

            raise ExecutionMarketDataError(
                "Execution market result must "
                "contain exactly one row."
            )

        row_date = (
            pd.Timestamp(
                result.data.index[0]
            )
            .date()
        )

        if (
            row_date
            != self.execution_session
        ):

            raise ExecutionMarketDataError(
                "Execution result belongs to "
                "the wrong market session."
            )

        return DataQualityReport(
            ticker=result.ticker,
            checked_at_utc=(
                result.retrieved_at_utc
            ),
            latest_data_session=(
                self.execution_session
            ),
            latest_expected_completed_session=(
                self.execution_session
            ),
            issues=(),
        )

    @staticmethod
    def observation_time(
        result: MarketDataResult,
    ) -> datetime:
        """
        The observation cannot precede retrieval.

        For Model 1 we conservatively use the
        retrieval timestamp itself as the observed
        timestamp.
        """

        return result.retrieved_at_utc