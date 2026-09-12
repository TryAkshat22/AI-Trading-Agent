from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import pandas_market_calendars as mcal


class ExecutionScheduleError(Exception):
    """Base exception for execution-scheduling failures."""


class InvalidSignalTimestampError(ExecutionScheduleError):
    """Raised when a signal timestamp is unusable."""


class IntradaySignalError(ExecutionScheduleError):
    """
    Raised when a Model 1 signal is generated during
    regular market hours.

    Model 1 deliberately supports only:
        completed-session analysis
        -> next-session open execution
    """


class NoExecutionSessionError(ExecutionScheduleError):
    """Raised when a future executable session cannot be found."""


@dataclass(frozen=True)
class ExecutionPlan:
    """
    Immutable execution schedule for one trading signal.
    """

    signal_timestamp_utc: datetime

    source_session: date
    execution_session: date

    source_close_utc: datetime
    execution_open_utc: datetime

    calendar_name: str


class ExecutionScheduler:
    """
    Determines the next legal execution session for Model 1.

    Model 1 timing rule:

        Day T completes
              ↓
        signal generated
              ↓
        next valid NYSE session
              ↓
        execute at that session's raw Open

    Signals generated during regular market hours are rejected.

    Signals generated:
    - after market close
    - overnight
    - during weekends
    - during exchange holidays
    - before the next market open

    are allowed.
    """

    def __init__(
        self,
        calendar_name: str = "NYSE",
    ) -> None:

        self.calendar_name = calendar_name

        self.calendar = mcal.get_calendar(
            calendar_name
        )

    def create_plan(
        self,
        signal_timestamp: datetime,
    ) -> ExecutionPlan:
        """
        Create an execution plan from a signal timestamp.

        The supplied timestamp may use any timezone,
        but it must be timezone-aware.

        Internally, all timestamps are normalized to UTC.
        """

        signal_utc = self._normalize_to_utc(
            signal_timestamp
        )

        schedule = self._get_schedule(
            signal_utc
        )

        source_row = self._find_latest_completed_session(
            schedule=schedule,
            signal_utc=signal_utc,
        )

        if source_row is None:
            raise NoExecutionSessionError(
                "Could not identify a completed market "
                "session before the signal timestamp."
            )

        (
            source_session,
            source_close,
        ) = source_row

        execution_row = self._find_next_session(
            schedule=schedule,
            source_session=source_session,
        )

        if execution_row is None:
            raise NoExecutionSessionError(
                "Could not identify the next NYSE "
                "session after the source session."
            )

        (
            execution_session,
            execution_open,
        ) = execution_row

        # Important Model 1 safeguard:
        #
        # If the next session has already opened, then this signal
        # was generated during a live trading session.
        #
        # We do NOT silently move it to the following day because
        # that would change the strategy definition.
        if signal_utc >= execution_open:

            execution_schedule = schedule.loc[
                pd.Timestamp(
                    execution_session
                )
            ]

            execution_close = (
                execution_schedule[
                    "market_close"
                ].to_pydatetime()
            )

            if signal_utc < execution_close:
                raise IntradaySignalError(
                    "Model 1 does not accept signals "
                    "generated during regular market hours."
                )

            # This should normally be impossible because a
            # completed session would then have become the
            # source session. Treat it as a scheduling error
            # rather than guessing.
            raise ExecutionScheduleError(
                "Signal timestamp is inconsistent with "
                "the calculated execution session."
            )

        return ExecutionPlan(
            signal_timestamp_utc=signal_utc,
            source_session=source_session,
            execution_session=execution_session,
            source_close_utc=source_close,
            execution_open_utc=execution_open,
            calendar_name=self.calendar_name,
        )

    def _get_schedule(
        self,
        signal_utc: datetime,
    ) -> pd.DataFrame:
        """
        Load enough historical and future exchange sessions
        to handle weekends and extended holiday periods.
        """

        start_date = (
            signal_utc.date()
            - timedelta(days=30)
        )

        end_date = (
            signal_utc.date()
            + timedelta(days=30)
        )

        schedule = self.calendar.schedule(
            start_date=start_date,
            end_date=end_date,
            tz="UTC",
        )

        if schedule.empty:
            raise ExecutionScheduleError(
                "Exchange calendar returned no sessions."
            )

        return schedule

    @staticmethod
    def _find_latest_completed_session(
        schedule: pd.DataFrame,
        signal_utc: datetime,
    ) -> tuple[date, datetime] | None:

        signal_timestamp = pd.Timestamp(
            signal_utc
        )

        completed = schedule[
            schedule["market_close"]
            <= signal_timestamp
        ]

        if completed.empty:
            return None

        source_index = completed.index[-1]

        source_session = (
            pd.Timestamp(
                source_index
            ).date()
        )

        source_close = (
            completed.iloc[-1][
                "market_close"
            ].to_pydatetime()
        )

        return (
            source_session,
            source_close,
        )

    @staticmethod
    def _find_next_session(
        schedule: pd.DataFrame,
        source_session: date,
    ) -> tuple[date, datetime] | None:

        source_timestamp = pd.Timestamp(
            source_session
        )

        future = schedule[
            schedule.index
            > source_timestamp
        ]

        if future.empty:
            return None

        next_index = future.index[0]

        execution_session = (
            pd.Timestamp(
                next_index
            ).date()
        )

        execution_open = (
            future.iloc[0][
                "market_open"
            ].to_pydatetime()
        )

        return (
            execution_session,
            execution_open,
        )

    @staticmethod
    def _normalize_to_utc(
        timestamp: datetime,
    ) -> datetime:
        """
        Require timezone awareness and normalize to UTC.
        """

        if timestamp.tzinfo is None:
            raise InvalidSignalTimestampError(
                "Signal timestamp must be "
                "timezone-aware."
            )

        return timestamp.astimezone(
            timezone.utc
        )


def create_execution_plan(
    signal_timestamp: datetime,
) -> ExecutionPlan:
    """
    Public scheduling entry point.
    """

    scheduler = ExecutionScheduler()

    return scheduler.create_plan(
        signal_timestamp
    )