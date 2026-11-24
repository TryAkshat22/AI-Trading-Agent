
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import quote

from database.storage import get_default_database_path
from services.intraday_collector import IntradayObservation
from trading.flexible_execution_observation import (
    FlexibleExecutionObservation,
    FlexibleExecutionObservationError,
    FlexibleExecutionObservationValidator,
)


class FlexibleObservationSelectionError(Exception):
    """A suitable stored observation could not be selected."""


class FlexibleObservationSelector:
    """
    Read-only selector for previously collected intraday data.

    Selects the most recently retrieved observation available
    at the requested check time, then validates it.

    It never:
      - fetches new prices
      - creates orders
      - creates fills
      - updates account balances
      - changes pending-order status
    """

    def __init__(
        self,
        database_path: str | Path | None = None,
        validator: FlexibleExecutionObservationValidator | None = None,
    ) -> None:
        self.database_path = Path(
            database_path
            if database_path is not None
            else get_default_database_path()
        ).expanduser()

        self.validator = (
            validator
            if validator is not None
            else FlexibleExecutionObservationValidator()
        )

    @staticmethod
    def _parse_time(value: str) -> datetime:
        try:
            parsed = datetime.fromisoformat(
                value.replace("Z", "+00:00")
            )
        except (TypeError, ValueError) as exc:
            raise FlexibleObservationSelectionError(
                "Stored observation contains an invalid timestamp."
            ) from exc

        if parsed.tzinfo is None:
            raise FlexibleObservationSelectionError(
                "Stored observation timestamp is timezone-naive."
            )

        return parsed.astimezone(timezone.utc)

    def _load_observations(
        self,
        ticker: str,
    ) -> list[IntradayObservation]:
        if not self.database_path.is_file():
            raise FlexibleObservationSelectionError(
                "Intraday observation database does not exist."
            )

        # Open SQLite in read-only mode. Do not create a missing
        # database or modify any trading tables.
        database_uri = (
            "file:"
            + quote(
                self.database_path.resolve().as_posix(),
                safe="/:",
            )
            + "?mode=ro"
        )

        try:
            with sqlite3.connect(
                database_uri,
                uri=True,
                timeout=10,
            ) as connection:
                rows = connection.execute(
                    """
                    SELECT
                        ticker,
                        provider,
                        bar_start_utc,
                        retrieved_at_utc,
                        open_price,
                        high_price,
                        low_price,
                        close_price,
                        volume
                    FROM intraday_observations
                    WHERE ticker = ?
                    """,
                    (ticker,),
                ).fetchall()

        except sqlite3.Error as exc:
            raise FlexibleObservationSelectionError(
                f"Cannot read stored intraday observations: {exc}"
            ) from exc

        return [
            IntradayObservation(
                ticker=row[0],
                provider=row[1],
                bar_start_utc=self._parse_time(row[2]),
                retrieved_at_utc=self._parse_time(row[3]),
                open=row[4],
                high=row[5],
                low=row[6],
                close=row[7],
                volume=row[8],
            )
            for row in rows
        ]

    def select(
        self,
        ticker: str,
        execution_session: date,
        checked_at: datetime,
    ) -> FlexibleExecutionObservation:
        ticker = ticker.strip().upper()

        if not ticker:
            raise ValueError("Ticker cannot be blank.")

        if checked_at.tzinfo is None:
            raise FlexibleObservationSelectionError(
                "checked_at must be timezone-aware."
            )

        checked_utc = checked_at.astimezone(timezone.utc)

        observations = self._load_observations(ticker)

        # A future retrieval must never be used to justify
        # an earlier simulated execution.
        available = [
            observation
            for observation in observations
            if (
                observation.retrieved_at_utc <= checked_utc
                and observation.bar_start_utc.date()
                == execution_session
            )
        ]

        if not available:
            raise FlexibleObservationSelectionError(
                f"No observation for {ticker} was available "
                f"by {checked_utc.isoformat()} on "
                f"{execution_session}."
            )

        # Select the latest available observation. If it is
        # stale or invalid, fail rather than substituting an
        # older observation.
        selected = max(
            available,
            key=lambda observation: (
                observation.retrieved_at_utc,
                observation.bar_start_utc,
            ),
        )

        try:
            return self.validator.validate(
                observation=selected,
                execution_session=execution_session,
                checked_at=checked_utc,
                expected_ticker=ticker,
            )

        except FlexibleExecutionObservationError as exc:
            raise FlexibleObservationSelectionError(
                f"Latest observation for {ticker} "
                f"cannot support execution: {exc}"
            ) from exc