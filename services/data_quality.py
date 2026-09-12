from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from enum import Enum

import pandas as pd
import pandas_market_calendars as mcal

from services.market_data import MarketDataResult


class Severity(str, Enum):
    CRITICAL = "CRITICAL"
    WARNING = "WARNING"
    INFO = "INFO"


@dataclass(frozen=True)
class DataQualityIssue:
    severity: Severity
    code: str
    message: str


@dataclass(frozen=True)
class DataQualityReport:
    ticker: str
    checked_at_utc: datetime
    latest_data_session: date | None
    latest_expected_completed_session: date | None
    issues: tuple[DataQualityIssue, ...]

    @property
    def safe_to_use(self) -> bool:
        """
        Data is safe only if no CRITICAL issues exist.
        """
        return not any(
            issue.severity == Severity.CRITICAL
            for issue in self.issues
        )

    @property
    def warnings(self) -> tuple[DataQualityIssue, ...]:
        return tuple(
            issue
            for issue in self.issues
            if issue.severity == Severity.WARNING
        )

    @property
    def critical_issues(self) -> tuple[DataQualityIssue, ...]:
        return tuple(
            issue
            for issue in self.issues
            if issue.severity == Severity.CRITICAL
        )


class MarketDataQualityValidator:
    """
    Validates daily US-equity market data against an exchange calendar.

    Version 1 assumes the NYSE trading calendar.

    Responsibilities:
    - Detect missing trading sessions
    - Detect unexpected/non-trading dates
    - Detect stale datasets
    - Detect incomplete current-session data
    - Surface provider repair flags

    This class does NOT modify market data.
    It only evaluates and reports its quality.
    """

    def __init__(
        self,
        calendar_name: str = "NYSE",
    ) -> None:
        self.calendar_name = calendar_name
        self.calendar = mcal.get_calendar(calendar_name)

    def validate(
        self,
        result: MarketDataResult,
        now_utc: datetime | None = None,
    ) -> DataQualityReport:

        if now_utc is None:
            now_utc = datetime.now(timezone.utc)

        if now_utc.tzinfo is None:
            raise ValueError(
                "now_utc must be timezone-aware."
            )

        issues: list[DataQualityIssue] = []

        data = result.data.copy()

        if data.empty:
            issues.append(
                DataQualityIssue(
                    severity=Severity.CRITICAL,
                    code="EMPTY_DATA",
                    message="Dataset contains no rows.",
                )
            )

            return DataQualityReport(
                ticker=result.ticker,
                checked_at_utc=now_utc,
                latest_data_session=None,
                latest_expected_completed_session=None,
                issues=tuple(issues),
            )

        session_dates = self._extract_session_dates(data)

        latest_data_session = max(session_dates)

        latest_expected_completed_session = (
            self._latest_completed_session(now_utc)
        )

        self._check_missing_sessions(
            session_dates=session_dates,
            issues=issues,
        )

        self._check_unexpected_sessions(
            session_dates=session_dates,
            issues=issues,
        )

        self._check_freshness(
            latest_data_session=latest_data_session,
            latest_expected_completed_session=(
                latest_expected_completed_session
            ),
            issues=issues,
        )

        self._check_incomplete_session(
            session_dates=session_dates,
            latest_expected_completed_session=(
                latest_expected_completed_session
            ),
            now_utc=now_utc,
            issues=issues,
        )

        self._check_provider_repairs(
            data=data,
            issues=issues,
        )

        if not issues:
            issues.append(
                DataQualityIssue(
                    severity=Severity.INFO,
                    code="DATA_OK",
                    message=(
                        "No calendar, freshness, or repair "
                        "issues detected."
                    ),
                )
            )

        return DataQualityReport(
            ticker=result.ticker,
            checked_at_utc=now_utc,
            latest_data_session=latest_data_session,
            latest_expected_completed_session=(
                latest_expected_completed_session
            ),
            issues=tuple(issues),
        )

    @staticmethod
    def _extract_session_dates(
        data: pd.DataFrame,
    ) -> set[date]:

        timestamps = pd.to_datetime(data.index)

        return {
            timestamp.date()
            for timestamp in timestamps
        }

    def _valid_session_dates(
        self,
        start_date: date,
        end_date: date,
    ) -> set[date]:

        valid_days = self.calendar.valid_days(
            start_date=start_date,
            end_date=end_date,
            tz="UTC",
        )

        return {
            timestamp.date()
            for timestamp in valid_days
        }

    def _latest_completed_session(
        self,
        now_utc: datetime,
    ) -> date | None:
        """
        Determine the most recent NYSE session whose official
        market close has already occurred.
        """

        start_date = (
            now_utc.date() - timedelta(days=30)
        )

        end_date = now_utc.date()

        schedule = self.calendar.schedule(
            start_date=start_date,
            end_date=end_date,
            tz="UTC",
        )

        if schedule.empty:
            return None

        now_timestamp = pd.Timestamp(now_utc)

        completed = schedule[
            schedule["market_close"] <= now_timestamp
        ]

        if completed.empty:
            return None

        return completed.index[-1].date()

    def _check_missing_sessions(
        self,
        session_dates: set[date],
        issues: list[DataQualityIssue],
    ) -> None:

        first_session = min(session_dates)
        last_session = max(session_dates)

        expected_sessions = self._valid_session_dates(
            start_date=first_session,
            end_date=last_session,
        )

        missing_sessions = sorted(
            expected_sessions - session_dates
        )

        if missing_sessions:
            preview = ", ".join(
                str(day)
                for day in missing_sessions[:5]
            )

            if len(missing_sessions) > 5:
                preview += ", ..."

            issues.append(
                DataQualityIssue(
                    severity=Severity.CRITICAL,
                    code="MISSING_TRADING_SESSIONS",
                    message=(
                        f"{len(missing_sessions)} expected "
                        f"trading session(s) are missing: "
                        f"{preview}"
                    ),
                )
            )

    def _check_unexpected_sessions(
        self,
        session_dates: set[date],
        issues: list[DataQualityIssue],
    ) -> None:

        first_session = min(session_dates)
        last_session = max(session_dates)

        expected_sessions = self._valid_session_dates(
            start_date=first_session,
            end_date=last_session,
        )

        unexpected_sessions = sorted(
            session_dates - expected_sessions
        )

        if unexpected_sessions:
            preview = ", ".join(
                str(day)
                for day in unexpected_sessions[:5]
            )

            if len(unexpected_sessions) > 5:
                preview += ", ..."

            issues.append(
                DataQualityIssue(
                    severity=Severity.CRITICAL,
                    code="UNEXPECTED_TRADING_SESSIONS",
                    message=(
                        f"{len(unexpected_sessions)} row(s) "
                        f"occur on non-NYSE trading dates: "
                        f"{preview}"
                    ),
                )
            )

    @staticmethod
    def _check_freshness(
        latest_data_session: date,
        latest_expected_completed_session: date | None,
        issues: list[DataQualityIssue],
    ) -> None:

        if latest_expected_completed_session is None:
            issues.append(
                DataQualityIssue(
                    severity=Severity.CRITICAL,
                    code="NO_COMPLETED_SESSION_FOUND",
                    message=(
                        "Could not determine the latest "
                        "completed exchange session."
                    ),
                )
            )
            return

        if latest_data_session < latest_expected_completed_session:
            issues.append(
                DataQualityIssue(
                    severity=Severity.CRITICAL,
                    code="STALE_DATA",
                    message=(
                        f"Latest dataset session is "
                        f"{latest_data_session}, but the latest "
                        f"completed market session is "
                        f"{latest_expected_completed_session}."
                    ),
                )
            )

    def _check_incomplete_session(
        self,
        session_dates: set[date],
        latest_expected_completed_session: date | None,
        now_utc: datetime,
        issues: list[DataQualityIssue],
    ) -> None:

        if latest_expected_completed_session is None:
            return

        future_or_incomplete = sorted(
            session_date
            for session_date in session_dates
            if session_date > latest_expected_completed_session
        )

        if not future_or_incomplete:
            return

        today = now_utc.date()

        for session_date in future_or_incomplete:

            if session_date > today:
                issues.append(
                    DataQualityIssue(
                        severity=Severity.CRITICAL,
                        code="FUTURE_SESSION",
                        message=(
                            f"Dataset contains future session "
                            f"{session_date}."
                        ),
                    )
                )

            else:
                issues.append(
                    DataQualityIssue(
                        severity=Severity.WARNING,
                        code="INCOMPLETE_SESSION_PRESENT",
                        message=(
                            f"Dataset contains session "
                            f"{session_date}, but that session "
                            f"has not yet officially completed."
                        ),
                    )
                )

    @staticmethod
    def _check_provider_repairs(
        data: pd.DataFrame,
        issues: list[DataQualityIssue],
    ) -> None:

        if "Repaired?" not in data.columns:
            return

        repaired = data["Repaired?"].fillna(False)

        repaired_count = int(
            repaired.astype(bool).sum()
        )

        if repaired_count > 0:
            issues.append(
                DataQualityIssue(
                    severity=Severity.WARNING,
                    code="PROVIDER_REPAIRS",
                    message=(
                        f"Provider reports {repaired_count} "
                        f"repaired observation(s)."
                    ),
                )
            )


def validate_market_data(
    result: MarketDataResult,
    now_utc: datetime | None = None,
) -> DataQualityReport:
    """
    Public entry point for market-data quality validation.
    """

    validator = MarketDataQualityValidator()

    return validator.validate(
        result=result,
        now_utc=now_utc,
    )