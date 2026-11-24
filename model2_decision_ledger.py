
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4

from database.account_storage import AccountStorage
from model2_config import (
    MODEL_2_ACCOUNT_ID,
    MODEL_2_VERSION,
    get_model2_paths,
)


class Model2DecisionLedgerError(RuntimeError):
    """A decision-run ledger operation was blocked."""


class Model2DecisionAlreadyClaimedError(
    Model2DecisionLedgerError
):
    """A decision session already has a recorded run."""


@dataclass(frozen=True)
class Model2DecisionRunRecord:
    run_id: str
    decision_session: date
    model_version: str
    status: str
    started_at_utc: str
    finished_at_utc: str | None
    orders_created: int | None
    failed_tickers: int | None
    error_message: str | None


class Model2DecisionLedger:
    """
    Persistent Model 2 decision-run ledger.

    One run is permitted per decision session.

    STARTED, COMPLETED, and FAILED records all block
    another claim. A crashed STARTED run must be
    inspected rather than automatically restarted.

    This class never creates orders or fills.
    """

    def __init__(
        self,
        database_path: str | Path | None = None,
    ) -> None:
        paths = get_model2_paths()

        if database_path is None:
            database_path = paths.model2_database

        self.database_path = (
            Path(database_path).expanduser().resolve()
        )

        if self.database_path != paths.model2_database:
            raise Model2DecisionLedgerError(
                "Decision ledger must use the configured "
                "Model 2 trading database."
            )

        if self.database_path == paths.model1_database:
            raise Model2DecisionLedgerError(
                "Decision ledger cannot use Model 1's database."
            )

    def _verify_account(self) -> None:
        if not self.database_path.is_file():
            raise Model2DecisionLedgerError(
                "Model 2 database does not exist."
            )

        accounts = AccountStorage(self.database_path)

        account = accounts.get_account(
            MODEL_2_ACCOUNT_ID
        )

        if (
            account is None
            or accounts.count_accounts() != 1
        ):
            raise Model2DecisionLedgerError(
                "Model 2 database must contain exactly "
                "one account: model2-paper."
            )

    def _connect(self) -> sqlite3.Connection:
        self._verify_account()

        # mode=rw refuses to create a missing database.
        # Path.as_uri() handles Windows drive letters
        # and spaces in directory names.
        uri = self.database_path.as_uri() + "?mode=rw"

        connection = sqlite3.connect(
            uri,
            uri=True,
            timeout=10,
        )

        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 10000")

        return connection

    @staticmethod
    def _validate_session(
        decision_session: date,
    ) -> None:
        if (
            not isinstance(decision_session, date)
            or isinstance(decision_session, datetime)
        ):
            raise TypeError(
                "decision_session must be a datetime.date."
            )

    @staticmethod
    def _utc_timestamp(value: datetime) -> str:
        if (
            not isinstance(value, datetime)
            or value.tzinfo is None
            or value.utcoffset() is None
        ):
            raise ValueError(
                "Timestamp must be timezone-aware."
            )

        return value.astimezone(
            timezone.utc
        ).isoformat()

    @staticmethod
    def _to_record(
        row: sqlite3.Row,
    ) -> Model2DecisionRunRecord:
        return Model2DecisionRunRecord(
            run_id=row["run_id"],
            decision_session=date.fromisoformat(
                row["decision_session"]
            ),
            model_version=row["model_version"],
            status=row["status"],
            started_at_utc=row["started_at_utc"],
            finished_at_utc=row["finished_at_utc"],
            orders_created=row["orders_created"],
            failed_tickers=row["failed_tickers"],
            error_message=row["error_message"],
        )

    def initialize(self) -> None:
        """
        Create only the ledger table in the existing
        Model 2 database. Never create a database.
        """
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS
                model2_decision_runs (
                    run_id TEXT PRIMARY KEY,
                    decision_session TEXT NOT NULL,
                    model_version TEXT NOT NULL,
                    status TEXT NOT NULL
                        CHECK (
                            status IN (
                                'STARTED',
                                'COMPLETED',
                                'FAILED'
                            )
                        ),
                    started_at_utc TEXT NOT NULL,
                    finished_at_utc TEXT,
                    orders_created INTEGER
                        CHECK (
                            orders_created IS NULL
                            OR orders_created >= 0
                        ),
                    failed_tickers INTEGER
                        CHECK (
                            failed_tickers IS NULL
                            OR failed_tickers >= 0
                        ),
                    error_message TEXT,
                    UNIQUE (
                        decision_session,
                        model_version
                    )
                )
                """
            )

    def get_for_session(
        self,
        decision_session: date,
    ) -> Model2DecisionRunRecord | None:
        self._validate_session(decision_session)

        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM model2_decision_runs
                WHERE decision_session = ?
                  AND model_version = ?
                """,
                (
                    decision_session.isoformat(),
                    MODEL_2_VERSION,
                ),
            ).fetchone()

        return (
            self._to_record(row)
            if row is not None
            else None
        )

    def claim(
        self,
        decision_session: date,
        started_at: datetime,
    ) -> Model2DecisionRunRecord:
        """
        Atomically claim a session before running it.

        An existing STARTED, COMPLETED, or FAILED
        record prevents another claim.
        """
        self._validate_session(decision_session)
        started_at_utc = self._utc_timestamp(started_at)
        run_id = str(uuid4())

        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")

                connection.execute(
                    """
                    INSERT INTO model2_decision_runs (
                        run_id,
                        decision_session,
                        model_version,
                        status,
                        started_at_utc
                    )
                    VALUES (?, ?, ?, 'STARTED', ?)
                    """,
                    (
                        run_id,
                        decision_session.isoformat(),
                        MODEL_2_VERSION,
                        started_at_utc,
                    ),
                )

        except sqlite3.IntegrityError as exc:
            raise Model2DecisionAlreadyClaimedError(
                "This Model 2 decision session already "
                "has a run. Inspect it before retrying."
            ) from exc

        record = self.get_for_session(
            decision_session
        )

        if record is None:
            raise Model2DecisionLedgerError(
                "Claim was not found after persistence."
            )

        return record

    def finish(
        self,
        run_id: str,
        *,
        status: str,
        finished_at: datetime,
        orders_created: int,
        failed_tickers: int,
        error_message: str | None = None,
    ) -> Model2DecisionRunRecord:
        """
        Finalize one STARTED run exactly once.

        FAILED records are not automatically retryable.
        """
        if status not in ("COMPLETED", "FAILED"):
            raise ValueError(
                "Final status must be COMPLETED or FAILED."
            )

        if (
            type(orders_created) is not int
            or orders_created < 0
            or type(failed_tickers) is not int
            or failed_tickers < 0
        ):
            raise ValueError(
                "Outcome counts must be nonnegative integers."
            )

        if not isinstance(run_id, str) or not run_id.strip():
            raise ValueError("run_id cannot be blank.")

        finished_at_utc = self._utc_timestamp(
            finished_at
        )

        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE model2_decision_runs
                SET status = ?,
                    finished_at_utc = ?,
                    orders_created = ?,
                    failed_tickers = ?,
                    error_message = ?
                WHERE run_id = ?
                  AND status = 'STARTED'
                  AND started_at_utc <= ?
                """,
                (
                    status,
                    finished_at_utc,
                    orders_created,
                    failed_tickers,
                    error_message,
                    run_id,
                    finished_at_utc,
                ),
            )

            if cursor.rowcount != 1:
                raise Model2DecisionLedgerError(
                    "Run does not exist, is already final, "
                    "or has an invalid finish time."
                )

            row = connection.execute(
                """
                SELECT *
                FROM model2_decision_runs
                WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()

        if row is None:
            raise Model2DecisionLedgerError(
                "Finalized run could not be retrieved."
            )

        return self._to_record(row)