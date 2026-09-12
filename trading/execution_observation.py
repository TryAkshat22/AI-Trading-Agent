from __future__ import annotations

from dataclasses import dataclass
from datetime import (
    date,
    datetime,
    timedelta,
    timezone,
)

import pandas as pd
import pandas_market_calendars as mcal

from services.market_data import (
    MarketDataResult,
)


class ExecutionObservationError(Exception):
    """
    Base exception for execution-observation
    validation failures.
    """


class InvalidExecutionSessionError(
    ExecutionObservationError
):
    """
    Raised when execution_session is not a valid
    session on the configured market calendar.
    """


class NaiveExecutionObservationError(
    ExecutionObservationError
):
    """
    Raised when an execution observation timestamp
    is timezone-naive.
    """


class NaiveRetrievalTimestampError(
    ExecutionObservationError
):
    """
    Raised when market_result.retrieved_at_utc is
    timezone-naive.
    """


class ExecutionObservationBeforeOpenError(
    ExecutionObservationError
):
    """
    Raised when the execution observation claims to
    exist before the official market open.
    """


class ExecutionObservationTooLateError(
    ExecutionObservationError
):
    """
    Raised when an observation is too late to support
    the configured near-open execution assumption.
    """


class MarketDataRetrievedBeforeOpenError(
    ExecutionObservationError
):
    """
    Raised when market data containing the execution
    Open claims to have been retrieved before the
    official market open.
    """


class ObservationBeforeRetrievalError(
    ExecutionObservationError
):
    """
    Raised when execution_observed_at occurs before
    the market data was actually retrieved.
    """


class ExecutionSessionDataMissingError(
    ExecutionObservationError
):
    """
    Raised when the market-data snapshot does not
    contain exactly one row for execution_session.
    """


class ExecutionTickerMismatchError(
    ExecutionObservationError
):
    """
    Raised when the supplied execution data belongs
    to a different ticker.
    """


class InvalidExecutionOpenError(
    ExecutionObservationError
):
    """
    Raised when the raw execution Open is missing,
    non-numeric, or non-positive.
    """


@dataclass(frozen=True)
class ValidatedExecutionObservation:
    """
    Provenance and timing record for one validated
    execution observation.
    """

    ticker: str

    execution_session: date

    market_open_utc: datetime

    execution_observed_at_utc: datetime

    market_retrieved_at_utc: datetime

    raw_open: float

    calendar_name: str

    max_execution_delay: timedelta

    @property
    def seconds_after_open(
        self,
    ) -> float:
        """
        Number of seconds between the official market
        open and the execution observation.
        """

        return (
            self.execution_observed_at_utc
            - self.market_open_utc
        ).total_seconds()

    @property
    def seconds_after_retrieval(
        self,
    ) -> float:
        """
        Number of seconds between market-data retrieval
        and the execution observation.
        """

        return (
            self.execution_observed_at_utc
            - self.market_retrieved_at_utc
        ).total_seconds()


class ExecutionObservationValidator:
    """
    Forward-paper anti-lookahead guard for execution.

    This validator answers a different question from
    normal end-of-day market-data validation.

    Decision data asks:

        "Was this completed session safe to use?"

    Execution data asks:

        "Was this raw Open actually observed in time
         to support our claimed execution?"

    For Model 1 near-open execution, the following
    conditions must hold:

        official market open
                <=
        market retrieval
                <=
        execution observation
                <=
        market open + allowed delay

    The execution dataset must also contain exactly one
    row for the intended execution session.

    This is deliberately strict. If the data provider
    cannot provide an execution observation quickly
    enough, forward-paper execution should fail closed
    rather than silently turn into historical replay.
    """

    def __init__(
        self,
        calendar_name: str = "NYSE",
        max_execution_delay: timedelta = timedelta(
            minutes=5
        ),
    ) -> None:

        calendar_name = (
            calendar_name.strip()
        )

        if not calendar_name:
            raise ValueError(
                "calendar_name cannot be empty."
            )

        if (
            max_execution_delay
            < timedelta(0)
        ):
            raise ValueError(
                "max_execution_delay cannot "
                "be negative."
            )

        self.calendar_name = (
            calendar_name
        )

        self.max_execution_delay = (
            max_execution_delay
        )

        try:
            self.calendar = (
                mcal.get_calendar(
                    calendar_name
                )
            )

        except Exception as exc:
            raise ValueError(
                "Unknown or unavailable market "
                f"calendar: {calendar_name}."
            ) from exc

    def validate(
        self,
        market_result: MarketDataResult,
        execution_session: date,
        execution_observed_at: datetime,
        expected_ticker: str | None = None,
    ) -> ValidatedExecutionObservation:
        """
        Validate whether an execution Open was genuinely
        available inside the permitted execution window.
        """

        if not isinstance(
            execution_session,
            date,
        ):
            raise TypeError(
                "execution_session must be "
                "a datetime.date."
            )

        if not isinstance(
            execution_observed_at,
            datetime,
        ):
            raise TypeError(
                "execution_observed_at must be "
                "a datetime.datetime."
            )

        if (
            execution_observed_at.tzinfo
            is None
        ):
            raise NaiveExecutionObservationError(
                "execution_observed_at must be "
                "timezone-aware."
            )

        retrieved_at = (
            market_result.retrieved_at_utc
        )

        if not isinstance(
            retrieved_at,
            datetime,
        ):
            raise TypeError(
                "market_result.retrieved_at_utc "
                "must be a datetime.datetime."
            )

        if retrieved_at.tzinfo is None:
            raise NaiveRetrievalTimestampError(
                "market_result.retrieved_at_utc "
                "must be timezone-aware."
            )

        observed_utc = (
            execution_observed_at.astimezone(
                timezone.utc
            )
        )

        retrieved_utc = (
            retrieved_at.astimezone(
                timezone.utc
            )
        )

        ticker = (
            str(
                market_result.ticker
            )
            .strip()
            .upper()
        )

        if not ticker:
            raise ExecutionTickerMismatchError(
                "Execution market result has "
                "an empty ticker."
            )

        if expected_ticker is not None:

            normalized_expected = (
                str(
                    expected_ticker
                )
                .strip()
                .upper()
            )

            if (
                ticker
                != normalized_expected
            ):
                raise ExecutionTickerMismatchError(
                    "Execution market-data ticker "
                    "does not match the expected "
                    "order ticker. "
                    f"Expected: {normalized_expected}. "
                    f"Received: {ticker}."
                )

        market_open_utc = (
            self._get_market_open(
                execution_session
            )
        )

        execution_deadline = (
            market_open_utc
            + self.max_execution_delay
        )

        if (
            observed_utc
            < market_open_utc
        ):
            raise (
                ExecutionObservationBeforeOpenError(
                    "Execution observation occurs "
                    "before the official market open. "
                    f"Observed: "
                    f"{observed_utc.isoformat()}. "
                    f"Market open: "
                    f"{market_open_utc.isoformat()}."
                )
            )

        if (
            retrieved_utc
            < market_open_utc
        ):
            raise (
                MarketDataRetrievedBeforeOpenError(
                    "Market data containing the "
                    "execution Open claims to have "
                    "been retrieved before the "
                    "official market open. "
                    f"Retrieved: "
                    f"{retrieved_utc.isoformat()}. "
                    f"Market open: "
                    f"{market_open_utc.isoformat()}."
                )
            )

        if (
            observed_utc
            < retrieved_utc
        ):
            raise (
                ObservationBeforeRetrievalError(
                    "Execution observation cannot "
                    "occur before the market data "
                    "was retrieved. "
                    f"Observed: "
                    f"{observed_utc.isoformat()}. "
                    f"Retrieved: "
                    f"{retrieved_utc.isoformat()}."
                )
            )

        if (
            observed_utc
            > execution_deadline
        ):
            raise ExecutionObservationTooLateError(
                "Execution observation occurs too "
                "late to support the configured "
                "near-open execution assumption. "
                f"Observed: "
                f"{observed_utc.isoformat()}. "
                f"Deadline: "
                f"{execution_deadline.isoformat()}."
            )

        raw_open = (
            self._extract_execution_open(
                market_result=market_result,
                execution_session=(
                    execution_session
                ),
            )
        )

        return ValidatedExecutionObservation(
            ticker=ticker,
            execution_session=(
                execution_session
            ),
            market_open_utc=(
                market_open_utc
            ),
            execution_observed_at_utc=(
                observed_utc
            ),
            market_retrieved_at_utc=(
                retrieved_utc
            ),
            raw_open=raw_open,
            calendar_name=(
                self.calendar_name
            ),
            max_execution_delay=(
                self.max_execution_delay
            ),
        )

    def _get_market_open(
        self,
        execution_session: date,
    ) -> datetime:
        """
        Resolve the official exchange open for exactly
        one execution session.

        Weekends and exchange holidays fail closed.
        """

        try:
            schedule = (
                self.calendar.schedule(
                    start_date=execution_session,
                    end_date=execution_session,
                )
            )

        except Exception as exc:
            raise ExecutionObservationError(
                "Failed to load market calendar "
                f"for {execution_session}."
            ) from exc

        if schedule.empty:
            raise InvalidExecutionSessionError(
                f"{execution_session} is not a "
                f"valid {self.calendar_name} "
                "trading session."
            )

        if len(schedule) != 1:
            raise ExecutionObservationError(
                "Market calendar returned an "
                "unexpected number of rows for "
                f"{execution_session}: "
                f"{len(schedule)}."
            )

        if (
            "market_open"
            not in schedule.columns
        ):
            raise ExecutionObservationError(
                "Market calendar schedule does "
                "not contain market_open."
            )

        timestamp = pd.Timestamp(
            schedule.iloc[0][
                "market_open"
            ]
        )

        if timestamp.tzinfo is None:
            raise ExecutionObservationError(
                "Market calendar returned a "
                "timezone-naive market-open "
                "timestamp."
            )

        return (
            timestamp
            .tz_convert("UTC")
            .to_pydatetime()
        )

    def _extract_execution_open(
        self,
        market_result: MarketDataResult,
        execution_session: date,
    ) -> float:
        """
        Extract exactly one raw Open from the intended
        execution session.
        """

        data = market_result.data

        if data is None:
            raise ExecutionSessionDataMissingError(
                "Execution market data is missing."
            )

        if data.empty:
            raise ExecutionSessionDataMissingError(
                "Execution market data is empty."
            )

        if "Open" not in data.columns:
            raise InvalidExecutionOpenError(
                "Execution market data does not "
                "contain raw Open."
            )

        try:
            session_mask = (
                pd.DatetimeIndex(
                    data.index
                ).date
                == execution_session
            )

        except Exception as exc:
            raise ExecutionSessionDataMissingError(
                "Execution market-data index "
                "could not be interpreted as "
                "session dates."
            ) from exc

        matching_rows = (
            data.loc[
                session_mask
            ]
        )

        if len(matching_rows) != 1:
            raise ExecutionSessionDataMissingError(
                "Execution market data must contain "
                "exactly one row for "
                f"{execution_session}. "
                f"Found: {len(matching_rows)}."
            )

        raw_value = (
            matching_rows.iloc[0][
                "Open"
            ]
        )

        try:
            raw_open = float(
                raw_value
            )

        except (
            TypeError,
            ValueError,
        ) as exc:
            raise InvalidExecutionOpenError(
                "Execution raw Open is not "
                "numeric."
            ) from exc

        if pd.isna(
            raw_open
        ):
            raise InvalidExecutionOpenError(
                "Execution raw Open is missing."
            )

        if raw_open <= 0:
            raise InvalidExecutionOpenError(
                "Execution raw Open must be "
                "positive."
            )

        return raw_open


def validate_execution_observation(
    market_result: MarketDataResult,
    execution_session: date,
    execution_observed_at: datetime,
    expected_ticker: str | None = None,
    calendar_name: str = "NYSE",
    max_execution_delay: timedelta = timedelta(
        minutes=5
    ),
) -> ValidatedExecutionObservation:
    """
    Convenience wrapper for one execution observation.
    """

    validator = (
        ExecutionObservationValidator(
            calendar_name=(
                calendar_name
            ),
            max_execution_delay=(
                max_execution_delay
            ),
        )
    )

    return validator.validate(
        market_result=market_result,
        execution_session=(
            execution_session
        ),
        execution_observed_at=(
            execution_observed_at
        ),
        expected_ticker=(
            expected_ticker
        ),
    )