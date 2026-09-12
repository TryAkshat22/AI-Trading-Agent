from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone

import pandas as pd
import pandas_market_calendars as mcal


class DecisionTimestampError(Exception):
    """
    Base exception for decision-timestamp
    validation failures.
    """


class InvalidSourceSessionError(
    DecisionTimestampError
):
    """
    Raised when source_session is not a valid
    trading session on the configured exchange.
    """


class DecisionBeforeCloseError(
    DecisionTimestampError
):
    """
    Raised when a decision claims to use a
    session's closing information before that
    session actually closed.
    """


class DecisionAfterExecutionOpenError(
    DecisionTimestampError
):
    """
    Raised when a decision is timestamped at or
    after the next valid execution-session open.
    """


class NaiveDecisionTimestampError(
    DecisionTimestampError
):
    """
    Raised when decision_timestamp has no
    timezone information.
    """


@dataclass(frozen=True)
class ValidatedDecisionTimestamp:
    """
    Validated anti-lookahead timing information
    for one Model 1 trading decision.
    """

    source_session: date

    decision_timestamp_utc: datetime

    source_close_utc: datetime

    next_execution_session: date

    next_execution_open_utc: datetime

    calendar_name: str

    @property
    def seconds_after_close(
        self,
    ) -> float:
        """
        Number of seconds between the official
        source-session close and the decision.

        Zero is valid.
        """

        return (
            self.decision_timestamp_utc
            - self.source_close_utc
        ).total_seconds()

    @property
    def seconds_before_execution_open(
        self,
    ) -> float:
        """
        Number of seconds remaining between the
        decision and the next execution-session open.

        This must always be greater than zero for
        a valid decision.
        """

        return (
            self.next_execution_open_utc
            - self.decision_timestamp_utc
        ).total_seconds()


class DecisionTimestampValidator:
    """
    Anti-lookahead timing guard for Model 1.

    A decision using completed-session market data
    is valid only inside this window:

        source session closes
                <=
        decision timestamp
                <
        next valid session opens

    This prevents two important errors:

    1. Using a session's Close before that Close
       was actually available.

    2. Treating a decision created after the next
       market open as though it were an overnight
       decision for that execution session.

    Exchange holidays, weekends, daylight-saving
    changes, and early closes are taken from
    pandas_market_calendars.
    """

    def __init__(
        self,
        calendar_name: str = "NYSE",
    ) -> None:

        calendar_name = (
            calendar_name.strip()
        )

        if not calendar_name:
            raise ValueError(
                "calendar_name cannot be empty."
            )

        self.calendar_name = (
            calendar_name
        )

        try:
            self.calendar = (
                mcal.get_calendar(
                    calendar_name
                )
            )

        except Exception as exc:
            raise ValueError(
                f"Unknown or unavailable "
                f"market calendar: "
                f"{calendar_name}."
            ) from exc

    def validate(
        self,
        source_session: date,
        decision_timestamp: datetime,
    ) -> ValidatedDecisionTimestamp:
        """
        Validate one decision timestamp.

        Requirements:

        - source_session must be a date
        - decision_timestamp must be timezone-aware
        - source_session must be a real market session
        - decision must be at/after official close
        - decision must be before next valid open
        """

        if not isinstance(
            source_session,
            date,
        ):
            raise TypeError(
                "source_session must be "
                "a datetime.date."
            )

        if not isinstance(
            decision_timestamp,
            datetime,
        ):
            raise TypeError(
                "decision_timestamp must be "
                "a datetime.datetime."
            )

        if (
            decision_timestamp.tzinfo
            is None
        ):
            raise NaiveDecisionTimestampError(
                "decision_timestamp must be "
                "timezone-aware."
            )

        decision_timestamp_utc = (
            decision_timestamp
            .astimezone(
                timezone.utc
            )
        )

        schedule = (
            self._load_schedule(
                source_session
            )
        )

        source_row = (
            self._find_source_session(
                schedule=schedule,
                source_session=(
                    source_session
                ),
            )
        )

        source_close_utc = (
            self._timestamp_to_utc_datetime(
                source_row[
                    "market_close"
                ]
            )
        )

        next_row = (
            self._find_next_session(
                schedule=schedule,
                source_session=(
                    source_session
                ),
            )
        )

        next_execution_session = (
            next_row.name.date()
        )

        next_execution_open_utc = (
            self._timestamp_to_utc_datetime(
                next_row[
                    "market_open"
                ]
            )
        )

        if (
            decision_timestamp_utc
            < source_close_utc
        ):
            raise DecisionBeforeCloseError(
                "Decision timestamp occurs "
                "before the source session "
                "officially closed. "
                f"Decision: "
                f"{decision_timestamp_utc.isoformat()}. "
                f"Source close: "
                f"{source_close_utc.isoformat()}."
            )

        if (
            decision_timestamp_utc
            >= next_execution_open_utc
        ):
            raise DecisionAfterExecutionOpenError(
                "Decision timestamp occurs "
                "at or after the next valid "
                "execution-session open. "
                f"Decision: "
                f"{decision_timestamp_utc.isoformat()}. "
                f"Next open: "
                f"{next_execution_open_utc.isoformat()}."
            )

        return ValidatedDecisionTimestamp(
            source_session=(
                source_session
            ),
            decision_timestamp_utc=(
                decision_timestamp_utc
            ),
            source_close_utc=(
                source_close_utc
            ),
            next_execution_session=(
                next_execution_session
            ),
            next_execution_open_utc=(
                next_execution_open_utc
            ),
            calendar_name=(
                self.calendar_name
            ),
        )

    def _load_schedule(
        self,
        source_session: date,
    ) -> pd.DataFrame:
        """
        Load a sufficiently wide calendar window
        around source_session.

        Seven days before covers validation context.

        Fourteen days after safely covers normal
        weekends and exchange holidays while still
        keeping calendar work small.
        """

        source_timestamp = pd.Timestamp(
            source_session
        )

        start_date = (
            source_timestamp
            - pd.Timedelta(
                days=7
            )
        ).date()

        end_date = (
            source_timestamp
            + pd.Timedelta(
                days=14
            )
        ).date()

        try:
            schedule = (
                self.calendar.schedule(
                    start_date=start_date,
                    end_date=end_date,
                )
            )

        except Exception as exc:
            raise DecisionTimestampError(
                "Failed to load market calendar "
                f"for {self.calendar_name}."
            ) from exc

        if schedule.empty:
            raise InvalidSourceSessionError(
                "Market calendar returned no "
                "sessions around "
                f"{source_session}."
            )

        required_columns = {
            "market_open",
            "market_close",
        }

        missing_columns = (
            required_columns
            - set(
                schedule.columns
            )
        )

        if missing_columns:
            raise DecisionTimestampError(
                "Market calendar schedule is "
                "missing required columns: "
                f"{sorted(missing_columns)}."
            )

        return schedule

    def _find_source_session(
        self,
        schedule: pd.DataFrame,
        source_session: date,
    ) -> pd.Series:
        """
        Return the exact schedule row for the
        requested source session.

        Weekends and market holidays therefore
        fail closed.
        """

        matches = schedule[
            schedule.index.date
            == source_session
        ]

        if matches.empty:
            raise InvalidSourceSessionError(
                f"{source_session} is not "
                f"a valid {self.calendar_name} "
                "trading session."
            )

        if len(matches) != 1:
            raise DecisionTimestampError(
                "Market calendar returned "
                "an unexpected number of rows "
                f"for {source_session}: "
                f"{len(matches)}."
            )

        return matches.iloc[0]

    def _find_next_session(
        self,
        schedule: pd.DataFrame,
        source_session: date,
    ) -> pd.Series:
        """
        Return the first valid market session
        strictly after source_session.
        """

        later_sessions = schedule[
            schedule.index.date
            > source_session
        ]

        if later_sessions.empty:
            raise DecisionTimestampError(
                "Could not determine the next "
                "valid execution session after "
                f"{source_session}."
            )

        return later_sessions.iloc[0]

    @staticmethod
    def _timestamp_to_utc_datetime(
        value,
    ) -> datetime:
        """
        Convert a pandas calendar timestamp into
        an explicitly UTC-aware datetime.

        Fails closed if the calendar unexpectedly
        produces a naive timestamp.
        """

        timestamp = pd.Timestamp(
            value
        )

        if timestamp.tzinfo is None:
            raise DecisionTimestampError(
                "Market calendar returned "
                "a timezone-naive timestamp."
            )

        return (
            timestamp
            .tz_convert("UTC")
            .to_pydatetime()
        )


def validate_decision_timestamp(
    source_session: date,
    decision_timestamp: datetime,
    calendar_name: str = "NYSE",
) -> ValidatedDecisionTimestamp:
    """
    Convenience wrapper for callers that do not
    need to retain a validator instance.
    """

    validator = (
        DecisionTimestampValidator(
            calendar_name=(
                calendar_name
            )
        )
    )

    return validator.validate(
        source_session=source_session,
        decision_timestamp=(
            decision_timestamp
        ),
    )