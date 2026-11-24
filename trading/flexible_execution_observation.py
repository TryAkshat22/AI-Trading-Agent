from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import pandas_market_calendars as mcal

from services.intraday_collector import IntradayObservation


class FlexibleExecutionObservationError(Exception):
    """An observation cannot support a paper execution."""


@dataclass(frozen=True)
class FlexibleExecutionObservation:
    ticker: str
    execution_session: date
    reference_price: float
    price_field: str
    provider: str
    bar_start_utc: datetime
    bar_end_utc: datetime
    retrieved_at_utc: datetime
    execution_checked_at_utc: datetime
    model: str


class FlexibleExecutionObservationValidator:
    """
    Validate a collected bar as a paper-execution
    price proxy.

    This component does not execute orders.

    It uses the Close of a completed 1-minute bar,
    never the historical 9:30 opening price by default.

    Default execution window:
      - starts 15 minutes after market open
      - ends 30 minutes before market close

    The actual exchange schedule is used, so early-close
    sessions automatically receive a shorter window.
    """

    MODEL = "flexible-observed-close-v1"

    def __init__(
        self,
        calendar_name: str = "NYSE",
        earliest_after_open: timedelta = timedelta(
            minutes=15
        ),
        latest_after_open: timedelta = timedelta(
            hours=6
        ),
        max_bar_age: timedelta = timedelta(
            minutes=5
        ),
        latest_before_close: timedelta = timedelta(
            minutes=30
        ),
    ) -> None:
        if earliest_after_open < timedelta(0):
            raise ValueError(
                "earliest_after_open cannot be negative."
            )

        if latest_after_open <= earliest_after_open:
            raise ValueError(
                "latest_after_open must exceed "
                "earliest_after_open."
            )

        if max_bar_age <= timedelta(0):
            raise ValueError(
                "max_bar_age must be positive."
            )

        if latest_before_close < timedelta(0):
            raise ValueError(
                "latest_before_close cannot be negative."
            )

        self.calendar = mcal.get_calendar(
            calendar_name
        )

        self.earliest_after_open = (
            earliest_after_open
        )

        self.latest_after_open = (
            latest_after_open
        )

        self.max_bar_age = max_bar_age

        self.latest_before_close = (
            latest_before_close
        )

    @staticmethod
    def _utc(
        value: datetime,
        field_name: str,
    ) -> datetime:
        if not isinstance(value, datetime):
            raise FlexibleExecutionObservationError(
                f"{field_name} must be a datetime."
            )

        if value.tzinfo is None:
            raise FlexibleExecutionObservationError(
                f"{field_name} must be timezone-aware."
            )

        return value.astimezone(timezone.utc)

    def validate(
        self,
        observation: IntradayObservation,
        execution_session: date,
        checked_at: datetime,
        expected_ticker: str,
    ) -> FlexibleExecutionObservation:

        if (
            not isinstance(execution_session, date)
            or isinstance(execution_session, datetime)
        ):
            raise TypeError(
                "execution_session must be a date."
            )

        checked = self._utc(
            checked_at,
            "checked_at",
        )

        retrieved = self._utc(
            observation.retrieved_at_utc,
            "retrieved_at_utc",
        )

        bar_start = self._utc(
            observation.bar_start_utc,
            "bar_start_utc",
        )

        ticker = observation.ticker.strip().upper()
        expected = expected_ticker.strip().upper()

        if not expected or ticker != expected:
            raise FlexibleExecutionObservationError(
                "Observation ticker does not match "
                "the requested order ticker."
            )

        if not observation.provider.strip():
            raise FlexibleExecutionObservationError(
                "Observation provider is missing."
            )

        schedule = self.calendar.schedule(
            start_date=execution_session,
            end_date=execution_session,
        )

        if len(schedule) != 1:
            raise FlexibleExecutionObservationError(
                "Execution session is not a valid "
                "exchange trading session."
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

        window_start = (
            market_open
            + self.earliest_after_open
        )

        window_end = min(
            market_open + self.latest_after_open,
            market_close - self.latest_before_close,
        )

        if window_end <= window_start:
            raise FlexibleExecutionObservationError(
                "Exchange session is too short to "
                "provide a valid flexible execution "
                "window."
            )

        if not (
            window_start <= checked < window_end
        ):
            raise FlexibleExecutionObservationError(
                "Current time is outside the flexible "
                "execution window."
            )

        bar_end = bar_start + timedelta(
            minutes=1
        )

        if not (
            market_open <= bar_start
            and bar_end <= market_close
        ):
            raise FlexibleExecutionObservationError(
                "Bar is outside the requested "
                "regular trading session."
            )

        if bar_end > retrieved:
            raise FlexibleExecutionObservationError(
                "Bar was not complete when retrieved."
            )

        if retrieved > checked:
            raise FlexibleExecutionObservationError(
                "Observation was retrieved after "
                "the proposed execution time."
            )

        if checked - bar_end > self.max_bar_age:
            raise FlexibleExecutionObservationError(
                "Observation is stale."
            )

        try:
            close_price = float(
                observation.close
            )

        except (TypeError, ValueError) as exc:
            raise FlexibleExecutionObservationError(
                "Observation Close is not numeric."
            ) from exc

        if (
            not math.isfinite(close_price)
            or close_price <= 0
        ):
            raise FlexibleExecutionObservationError(
                "Observation Close must be finite "
                "and positive."
            )

        return FlexibleExecutionObservation(
            ticker=ticker,
            execution_session=execution_session,
            reference_price=close_price,
            price_field="Close",
            provider=observation.provider,
            bar_start_utc=bar_start,
            bar_end_utc=bar_end,
            retrieved_at_utc=retrieved,
            execution_checked_at_utc=checked,
            model=self.MODEL,
        )