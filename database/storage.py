from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4

import pandas as pd

from sqlalchemy import (
    Boolean,
    Date,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    select,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    relationship,
)

from database.sqlite_engine import (
    create_sqlite_engine,
)
from services.data_quality import (
    DataQualityReport,
)
from services.market_data import (
    MarketDataResult,
)


class StorageError(Exception):
    """Base exception for market-data storage failures."""


class UnsafeMarketDataError(StorageError):
    """Raised when unsafe market data is sent to storage."""


# Backward-compatible alias for existing tests/code.
UnsafeDataError = UnsafeMarketDataError


class MarketDataTickerMismatchError(StorageError):
    """Raised when market result and quality report tickers differ."""


class Base(DeclarativeBase):
    pass


def utc_iso(
    value: datetime,
) -> str:
    """
    Convert a timezone-aware datetime to a normalized
    UTC ISO-8601 string.
    """

    if value.tzinfo is None:
        raise ValueError(
            "Datetime must be timezone-aware."
        )

    return (
        value.astimezone(
            timezone.utc
        )
        .isoformat()
    )


def get_default_database_path() -> Path:
    """
    Return the default SQLite path.

    The database is intentionally stored outside the
    OneDrive-synchronized project directory when possible.
    """

    env_path = os.getenv(
        "TRADING_AGENT_DB_PATH"
    )

    if env_path:
        return Path(
            env_path
        ).expanduser()

    local_app_data = os.getenv(
        "LOCALAPPDATA"
    )

    if local_app_data:
        return (
            Path(local_app_data)
            / "PaperTradingAgent"
            / "trading_agent.db"
        )

    return (
        Path.home()
        / ".paper_trading_agent"
        / "trading_agent.db"
    )


class IngestionRun(Base):
    """
    One immutable market-data ingestion event.
    """

    __tablename__ = "ingestion_runs"

    run_id: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
    )

    ticker: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        index=True,
    )

    provider: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    retrieved_at_utc: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
    )

    checked_at_utc: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
    )

    latest_data_session: Mapped[date | None] = (
        mapped_column(
            Date,
            nullable=True,
        )
    )

    latest_expected_session: Mapped[
    date | None
] = mapped_column(
        Date,
        nullable=True,
    )

    safe_to_use: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
    )

    issue_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    issues_json: Mapped[str] = mapped_column(
        String,
        nullable=False,
    )

    bars: Mapped[list["MarketBar"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
    )


class MarketBar(Base):
    """
    One historical market bar belonging to one
    specific ingestion run.
    """

    __tablename__ = "market_bars"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    run_id: Mapped[str] = mapped_column(
        ForeignKey(
            "ingestion_runs.run_id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    ticker: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        index=True,
    )

    session_date: Mapped[date] = (
        mapped_column(
            Date,
            nullable=False,
            index=True,
        )
    )

    open: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    high: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    low: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    close: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    adjusted_close: Mapped[float | None] = (
        mapped_column(
            Float,
            nullable=True,
        )
    )

    volume: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    dividend: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    stock_split: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    repaired: Mapped[bool | None] = mapped_column(
        Boolean,
        nullable=True,
    )

    run: Mapped[IngestionRun] = relationship(
        back_populates="bars"
    )

    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "ticker",
            "session_date",
            name="uq_market_bar_run_ticker_session",
        ),
    )


@dataclass(frozen=True)
class SaveResult:
    run_id: str
    ticker: str
    rows_saved: int
    database_path: Path


class MarketDataStorage:
    """
    Persistent storage for validated market-data snapshots.
    """

    def __init__(
        self,
        database_path: str | Path | None = None,
    ) -> None:

        if database_path is None:
            database_path = get_default_database_path()

        self.database_path = Path(
            database_path
        ).expanduser()

        self.database_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.engine = create_sqlite_engine(
            self.database_path
        )

    def initialize(self) -> None:
        """
        Create database tables if they do not already exist.
        """

        Base.metadata.create_all(
            self.engine
        )

    def save_market_snapshot(
    self,
    result: MarketDataResult,
    quality_report: DataQualityReport,
    ) -> SaveResult:
        """
        Persist one validated market-data ingestion run.

        Unsafe data is rejected.

        The ingestion run and all bars are committed in one
        transaction so storage is all-or-nothing.
        """

        ticker = (
            result.ticker
            .strip()
            .upper()
        )

        quality_ticker = (
            quality_report.ticker
            .strip()
            .upper()
        )

        if ticker != quality_ticker:
            raise MarketDataTickerMismatchError(
                "Market-data result ticker and "
                "quality-report ticker do not match."
            )

        if not quality_report.safe_to_use:
            raise UnsafeMarketDataError(
                f"{ticker} data failed the "
                "quality gate and cannot be stored."
            )

        run_id = str(
            uuid4()
        )

        issues = [
            {
                "severity": issue.severity.value,
                "code": issue.code,
                "message": issue.message,
            }
            for issue in quality_report.issues
        ]

        ingestion_run = IngestionRun(
            run_id=run_id,
            ticker=ticker,
            provider=result.provider,
            retrieved_at_utc=utc_iso(
                result.retrieved_at_utc
            ),
            checked_at_utc=utc_iso(
                quality_report.checked_at_utc
            ),
            latest_data_session=(
                quality_report
                .latest_data_session
            ),
            latest_expected_session=(
                quality_report
                .latest_expected_completed_session
            ),
            safe_to_use=(
                quality_report.safe_to_use
            ),
            issue_count=len(
                quality_report.issues
            ),
            issues_json=json.dumps(
                issues,
                sort_keys=True,
            ),
        )

        bars = self._convert_bars(
            run_id=run_id,
            ticker=ticker,
            data=result.data,
        )

        try:
            with Session(
                self.engine
            ) as session:

                session.add(
                    ingestion_run
                )

                session.add_all(
                    bars
                )

                session.commit()

        except Exception as exc:
            raise StorageError(
                f"Failed to save market snapshot "
                f"for {ticker}: {exc}"
            ) from exc

        return SaveResult(
            run_id=run_id,
            ticker=ticker,
            rows_saved=len(bars),
            database_path=(
                self.database_path
            ),
        )

    @staticmethod
    def _convert_bars(
        run_id: str,
        ticker: str,
        data: pd.DataFrame,
    ) -> list[MarketBar]:
        """
        Convert normalized provider data into ORM rows.
        """

        bars: list[MarketBar] = []

        for index, row in data.iterrows():

            session_date = (
                pd.Timestamp(
                    index
                ).date()
            )

            adjusted_close = None

            if (
                "Adj Close" in data.columns
                and pd.notna(
                    row.get(
                        "Adj Close"
                    )
                )
            ):
                adjusted_close = float(
                    row["Adj Close"]
                )

            volume = None

            if (
                "Volume" in data.columns
                and pd.notna(
                    row.get(
                        "Volume"
                    )
                )
            ):
                volume = float(
                    row["Volume"]
                )

            dividend = None

            if (
                "Dividends" in data.columns
                and pd.notna(
                    row.get(
                        "Dividends"
                    )
                )
            ):
                dividend = float(
                    row["Dividends"]
                )

            stock_split = None

            if (
                "Stock Splits" in data.columns
                and pd.notna(
                    row.get(
                        "Stock Splits"
                    )
                )
            ):
                stock_split = float(
                    row["Stock Splits"]
                )

            repaired = None

            if (
                "Repaired?" in data.columns
                and pd.notna(
                    row.get(
                        "Repaired?"
                    )
                )
            ):
                repaired = bool(
                    row["Repaired?"]
                )

            bars.append(
                MarketBar(
                    run_id=run_id,
                    ticker=ticker,
                    session_date=session_date,
                    open=float(
                        row["Open"]
                    ),
                    high=float(
                        row["High"]
                    ),
                    low=float(
                        row["Low"]
                    ),
                    close=float(
                        row["Close"]
                    ),
                    adjusted_close=(
                        adjusted_close
                    ),
                    volume=volume,
                    dividend=dividend,
                    stock_split=(
                        stock_split
                    ),
                    repaired=repaired,
                )
            )

        return bars

    def count_ingestion_runs(
        self,
    ) -> int:

        with Session(
            self.engine
        ) as session:

            return len(
                session.scalars(
                    select(
                        IngestionRun
                    )
                ).all()
            )

    def count_market_bars(
        self,
    ) -> int:

        with Session(
            self.engine
        ) as session:

            return len(
                session.scalars(
                    select(
                        MarketBar
                    )
                ).all()
            )

    def get_latest_run(
        self,
        ticker: str,
    ) -> IngestionRun | None:
        """
        Return the most recently stored ingestion run
        for a ticker.
        """

        ticker = (
            ticker
            .strip()
            .upper()
        )

        with Session(
            self.engine
        ) as session:

            statement = (
                select(
                    IngestionRun
                )
                .where(
                    IngestionRun.ticker
                    == ticker
                )
                .order_by(
                    IngestionRun
                    .retrieved_at_utc
                    .desc()
                )
            )

            return session.scalars(
                statement
            ).first()
        