from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from sqlalchemy import text

from database.sqlite_engine import create_sqlite_engine
from database.storage import get_default_database_path


class EquityStorageError(Exception):
    pass


class EquitySnapshotConflictError(
    EquityStorageError
):
    pass


@dataclass(frozen=True)
class EquitySnapshot:
    snapshot_id: str
    account_id: str
    model_version: str
    valuation_session: date

    starting_cash: Decimal
    cash: Decimal
    market_value: Decimal
    total_equity: Decimal

    realized_pnl: Decimal
    unrealized_pnl: Decimal
    total_pnl: Decimal

    total_return_pct: Decimal
    exposure_pct: Decimal

    open_positions: int
    recorded_at_utc: datetime


class EquityStorage:
    """
    Persistent daily portfolio-equity history.

    One immutable snapshot is allowed per:

        account_id
        + model_version
        + valuation_session

    Exact duplicate saves are idempotent.
    Different values for an existing session fail closed.
    """

    def __init__(
        self,
        database_path: str | Path | None = None,
    ) -> None:

        if database_path is None:
            database_path = (
                get_default_database_path()
            )

        self.database_path = Path(
            database_path
        )

        self.engine = create_sqlite_engine(
            self.database_path
        )

    def initialize(
        self,
    ) -> None:

        ddl = """
        CREATE TABLE IF NOT EXISTS equity_snapshots (
            snapshot_id TEXT PRIMARY KEY,
            account_id TEXT NOT NULL,
            model_version TEXT NOT NULL,
            valuation_session TEXT NOT NULL,

            starting_cash TEXT NOT NULL,
            cash TEXT NOT NULL,
            market_value TEXT NOT NULL,
            total_equity TEXT NOT NULL,

            realized_pnl TEXT NOT NULL,
            unrealized_pnl TEXT NOT NULL,
            total_pnl TEXT NOT NULL,

            total_return_pct TEXT NOT NULL,
            exposure_pct TEXT NOT NULL,

            open_positions INTEGER NOT NULL,
            recorded_at_utc TEXT NOT NULL,

            UNIQUE (
                account_id,
                model_version,
                valuation_session
            )
        )
        """

        with self.engine.begin() as connection:
            connection.execute(
                text(
                    ddl
                )
            )

    @staticmethod
    def _decimal_text(
        value,
    ) -> str:

        return str(
            Decimal(
                str(
                    value
                )
            )
        )

    @staticmethod
    def _utc_now() -> datetime:

        return datetime.now(
            timezone.utc
        )

    @staticmethod
    def _row_to_snapshot(
        row,
    ) -> EquitySnapshot:

        return EquitySnapshot(
            snapshot_id=(
                row[
                    "snapshot_id"
                ]
            ),
            account_id=(
                row[
                    "account_id"
                ]
            ),
            model_version=(
                row[
                    "model_version"
                ]
            ),
            valuation_session=(
                date.fromisoformat(
                    row[
                        "valuation_session"
                    ]
                )
            ),
            starting_cash=Decimal(
                row[
                    "starting_cash"
                ]
            ),
            cash=Decimal(
                row[
                    "cash"
                ]
            ),
            market_value=Decimal(
                row[
                    "market_value"
                ]
            ),
            total_equity=Decimal(
                row[
                    "total_equity"
                ]
            ),
            realized_pnl=Decimal(
                row[
                    "realized_pnl"
                ]
            ),
            unrealized_pnl=Decimal(
                row[
                    "unrealized_pnl"
                ]
            ),
            total_pnl=Decimal(
                row[
                    "total_pnl"
                ]
            ),
            total_return_pct=Decimal(
                row[
                    "total_return_pct"
                ]
            ),
            exposure_pct=Decimal(
                row[
                    "exposure_pct"
                ]
            ),
            open_positions=int(
                row[
                    "open_positions"
                ]
            ),
            recorded_at_utc=(
                datetime.fromisoformat(
                    row[
                        "recorded_at_utc"
                    ]
                )
            ),
        )

    def get_snapshot(
        self,
        valuation_session: date,
        account_id: str = "model1-paper",
        model_version: str = "model-1",
    ) -> EquitySnapshot | None:

        query = """
        SELECT *
        FROM equity_snapshots
        WHERE account_id = :account_id
          AND model_version = :model_version
          AND valuation_session = :valuation_session
        """

        with self.engine.connect() as connection:

            row = (
                connection.execute(
                    text(
                        query
                    ),
                    {
                        "account_id": account_id,
                        "model_version": model_version,
                        "valuation_session": (
                            valuation_session.isoformat()
                        ),
                    },
                )
                .mappings()
                .first()
            )

        if row is None:
            return None

        return self._row_to_snapshot(
            row
        )

    def save_snapshot(
        self,
        *,
        valuation_session: date,
        starting_cash,
        cash,
        market_value,
        total_equity,
        realized_pnl,
        unrealized_pnl,
        total_pnl,
        total_return_pct,
        exposure_pct,
        open_positions: int,
        account_id: str = "model1-paper",
        model_version: str = "model-1",
        recorded_at_utc: datetime | None = None,
    ) -> EquitySnapshot:

        if recorded_at_utc is None:
            recorded_at_utc = (
                self._utc_now()
            )

        if recorded_at_utc.tzinfo is None:

            raise ValueError(
                "recorded_at_utc must be "
                "timezone-aware."
            )

        recorded_at_utc = (
            recorded_at_utc.astimezone(
                timezone.utc
            )
        )

        values = {
            "starting_cash": self._decimal_text(
                starting_cash
            ),
            "cash": self._decimal_text(
                cash
            ),
            "market_value": self._decimal_text(
                market_value
            ),
            "total_equity": self._decimal_text(
                total_equity
            ),
            "realized_pnl": self._decimal_text(
                realized_pnl
            ),
            "unrealized_pnl": self._decimal_text(
                unrealized_pnl
            ),
            "total_pnl": self._decimal_text(
                total_pnl
            ),
            "total_return_pct": self._decimal_text(
                total_return_pct
            ),
            "exposure_pct": self._decimal_text(
                exposure_pct
            ),
        }

        if open_positions < 0:

            raise ValueError(
                "open_positions cannot be negative."
            )

        existing = self.get_snapshot(
            valuation_session=(
                valuation_session
            ),
            account_id=account_id,
            model_version=model_version,
        )

        if existing is not None:

            exact_match = (
                existing.starting_cash
                == Decimal(
                    values[
                        "starting_cash"
                    ]
                )
                and existing.cash
                == Decimal(
                    values[
                        "cash"
                    ]
                )
                and existing.market_value
                == Decimal(
                    values[
                        "market_value"
                    ]
                )
                and existing.total_equity
                == Decimal(
                    values[
                        "total_equity"
                    ]
                )
                and existing.realized_pnl
                == Decimal(
                    values[
                        "realized_pnl"
                    ]
                )
                and existing.unrealized_pnl
                == Decimal(
                    values[
                        "unrealized_pnl"
                    ]
                )
                and existing.total_pnl
                == Decimal(
                    values[
                        "total_pnl"
                    ]
                )
                and existing.total_return_pct
                == Decimal(
                    values[
                        "total_return_pct"
                    ]
                )
                and existing.exposure_pct
                == Decimal(
                    values[
                        "exposure_pct"
                    ]
                )
                and existing.open_positions
                == open_positions
            )

            if exact_match:
                return existing

            raise EquitySnapshotConflictError(
                "A different equity snapshot already "
                f"exists for {account_id}, "
                f"{model_version}, "
                f"{valuation_session}."
            )

        snapshot_id = str(
            uuid4()
        )

        insert = """
        INSERT INTO equity_snapshots (
            snapshot_id,
            account_id,
            model_version,
            valuation_session,
            starting_cash,
            cash,
            market_value,
            total_equity,
            realized_pnl,
            unrealized_pnl,
            total_pnl,
            total_return_pct,
            exposure_pct,
            open_positions,
            recorded_at_utc
        )
        VALUES (
            :snapshot_id,
            :account_id,
            :model_version,
            :valuation_session,
            :starting_cash,
            :cash,
            :market_value,
            :total_equity,
            :realized_pnl,
            :unrealized_pnl,
            :total_pnl,
            :total_return_pct,
            :exposure_pct,
            :open_positions,
            :recorded_at_utc
        )
        """

        with self.engine.begin() as connection:

            connection.execute(
                text(
                    insert
                ),
                {
                    "snapshot_id": snapshot_id,
                    "account_id": account_id,
                    "model_version": model_version,
                    "valuation_session": (
                        valuation_session.isoformat()
                    ),
                    **values,
                    "open_positions": (
                        open_positions
                    ),
                    "recorded_at_utc": (
                        recorded_at_utc.isoformat()
                    ),
                },
            )

        snapshot = self.get_snapshot(
            valuation_session=(
                valuation_session
            ),
            account_id=account_id,
            model_version=model_version,
        )

        if snapshot is None:

            raise EquityStorageError(
                "Snapshot could not be read "
                "after persistence."
            )

        return snapshot

    def list_snapshots(
        self,
        account_id: str = "model1-paper",
        model_version: str = "model-1",
    ) -> tuple[EquitySnapshot, ...]:

        query = """
        SELECT *
        FROM equity_snapshots
        WHERE account_id = :account_id
          AND model_version = :model_version
        ORDER BY valuation_session ASC
        """

        with self.engine.connect() as connection:

            rows = (
                connection.execute(
                    text(
                        query
                    ),
                    {
                        "account_id": account_id,
                        "model_version": model_version,
                    },
                )
                .mappings()
                .all()
            )

        return tuple(
            self._row_to_snapshot(
                row
            )
            for row in rows
        )

    def count_snapshots(
        self,
        account_id: str = "model1-paper",
        model_version: str = "model-1",
    ) -> int:

        query = """
        SELECT COUNT(*) AS count
        FROM equity_snapshots
        WHERE account_id = :account_id
          AND model_version = :model_version
        """

        with self.engine.connect() as connection:

            value = (
                connection.execute(
                    text(
                        query
                    ),
                    {
                        "account_id": account_id,
                        "model_version": model_version,
                    },
                )
                .scalar_one()
            )

        return int(
            value
        )