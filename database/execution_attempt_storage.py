from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import text

from database.sqlite_engine import (
    create_sqlite_engine,
)
from database.storage import (
    get_default_database_path,
)


class ExecutionAttemptStorageError(Exception):
    """
    Base exception for execution-attempt
    persistence failures.
    """


class ExecutionAttemptNotFoundError(
    ExecutionAttemptStorageError
):
    """
    Raised when the requested execution attempt
    does not exist.
    """


class InvalidExecutionAttemptStateError(
    ExecutionAttemptStorageError
):
    """
    Raised when an execution attempt would make an
    invalid state transition.
    """


class DuplicateExecutionAttemptError(
    ExecutionAttemptStorageError
):
    """
    Raised when the same order and execution snapshot
    are registered more than once.
    """


class ExecutionAttemptOutcome:
    """
    Stable execution-attempt outcome values.

    STARTED:
        observation accepted and execution is beginning

    FILLED:
        trade actually executed

    REJECTED:
        trading/risk rules deliberately prevented
        execution

    FAILED:
        execution workflow failed operationally while
        the order remained unfilled and unrejected
    """

    STARTED = "STARTED"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"

    TERMINAL = frozenset(
        {
            FILLED,
            REJECTED,
            FAILED,
        }
    )


@dataclass(frozen=True)
class ExecutionAttemptRecord:
    attempt_id: str

    order_id: str

    execution_run_id: str

    execution_observed_at_utc: datetime

    outcome: str

    created_at_utc: datetime

    completed_at_utc: datetime | None

    error_type: str | None

    error_message: str | None


class ExecutionAttemptStorage:
    """
    Persistent audit trail connecting an order to the
    exact execution snapshot used during an execution
    attempt.

    This intentionally lives separately from fills and
    rejections.

    Why?

        observation != trade

    An execution observation can lead to:

        FILLED
        REJECTED
        FAILED

    The observation remains historically important in
    every case.
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
        """
        Create the execution-attempt audit table.

        Raw DDL is deliberate here. It allows this small
        audit table to reference existing tables without
        modifying TradingStorage's SQLAlchemy metadata.
        """

        statement = text(
            """
            CREATE TABLE IF NOT EXISTS
            execution_attempts
            (
                attempt_id TEXT PRIMARY KEY,

                order_id TEXT NOT NULL,

                execution_run_id TEXT NOT NULL,

                execution_observed_at_utc
                    TEXT NOT NULL,

                outcome TEXT NOT NULL,

                created_at_utc TEXT NOT NULL,

                completed_at_utc TEXT,

                error_type TEXT,

                error_message TEXT,

                CONSTRAINT uq_execution_attempt
                    UNIQUE (
                        order_id,
                        execution_run_id
                    ),

                CONSTRAINT fk_execution_attempt_order
                    FOREIGN KEY (order_id)
                    REFERENCES paper_orders(order_id)
                    ON DELETE RESTRICT,

                CONSTRAINT fk_execution_attempt_run
                    FOREIGN KEY (execution_run_id)
                    REFERENCES ingestion_runs(run_id)
                    ON DELETE RESTRICT
            )
            """
        )

        with self.engine.begin() as connection:
            connection.execute(
                statement
            )

    def start_attempt(
        self,
        order_id: str,
        execution_run_id: str,
        execution_observed_at_utc: datetime,
        attempt_id: str | None = None,
    ) -> ExecutionAttemptRecord:
        """
        Persist the lineage link BEFORE execution begins.
        """

        order_id = self._normalize_required_text(
            order_id,
            "order_id",
        )

        execution_run_id = (
            self._normalize_required_text(
                execution_run_id,
                "execution_run_id",
            )
        )

        observed = self._normalize_utc_datetime(
            execution_observed_at_utc,
            "execution_observed_at_utc",
        )

        if attempt_id is None:
            attempt_id = str(
                uuid4()
            )

        attempt_id = (
            self._normalize_required_text(
                attempt_id,
                "attempt_id",
            )
        )

        now = datetime.now(
            timezone.utc
        )

        try:
            with self.engine.begin() as connection:

                existing = connection.execute(
                    text(
                        """
                        SELECT attempt_id
                        FROM execution_attempts
                        WHERE order_id = :order_id
                          AND execution_run_id =
                              :execution_run_id
                        """
                    ),
                    {
                        "order_id": order_id,
                        "execution_run_id": (
                            execution_run_id
                        ),
                    },
                ).first()

                if existing is not None:
                    raise (
                        DuplicateExecutionAttemptError(
                            "An execution attempt already "
                            "exists for order "
                            f"{order_id} and execution run "
                            f"{execution_run_id}."
                        )
                    )

                connection.execute(
                    text(
                        """
                        INSERT INTO execution_attempts
                        (
                            attempt_id,
                            order_id,
                            execution_run_id,
                            execution_observed_at_utc,
                            outcome,
                            created_at_utc,
                            completed_at_utc,
                            error_type,
                            error_message
                        )
                        VALUES
                        (
                            :attempt_id,
                            :order_id,
                            :execution_run_id,
                            :execution_observed_at_utc,
                            :outcome,
                            :created_at_utc,
                            NULL,
                            NULL,
                            NULL
                        )
                        """
                    ),
                    {
                        "attempt_id": attempt_id,
                        "order_id": order_id,
                        "execution_run_id": (
                            execution_run_id
                        ),
                        "execution_observed_at_utc": (
                            observed.isoformat()
                        ),
                        "outcome": (
                            ExecutionAttemptOutcome.STARTED
                        ),
                        "created_at_utc": (
                            now.isoformat()
                        ),
                    },
                )

        except DuplicateExecutionAttemptError:
            raise

        except Exception as exc:
            raise ExecutionAttemptStorageError(
                "Failed to persist execution attempt."
            ) from exc

        record = self.get_attempt(
            attempt_id
        )

        if record is None:
            raise ExecutionAttemptStorageError(
                "Execution attempt was inserted but "
                "could not be read back."
            )

        return record

    def finalize_attempt(
        self,
        attempt_id: str,
        outcome: str,
        error_type: str | None = None,
        error_message: str | None = None,
    ) -> ExecutionAttemptRecord:
        """
        Move STARTED -> one terminal outcome.

        Terminal attempts cannot be rewritten.
        """

        attempt_id = (
            self._normalize_required_text(
                attempt_id,
                "attempt_id",
            )
        )

        if (
            outcome
            not in ExecutionAttemptOutcome.TERMINAL
        ):
            raise ValueError(
                "outcome must be FILLED, "
                "REJECTED, or FAILED."
            )

        existing = self.get_attempt(
            attempt_id
        )

        if existing is None:
            raise ExecutionAttemptNotFoundError(
                f"Execution attempt does not exist: "
                f"{attempt_id}."
            )

        if (
            existing.outcome
            != ExecutionAttemptOutcome.STARTED
        ):
            raise InvalidExecutionAttemptStateError(
                "Only STARTED execution attempts can "
                "be finalized. "
                f"Current state: {existing.outcome}."
            )

        completed = datetime.now(
            timezone.utc
        )

        try:
            with self.engine.begin() as connection:

                result = connection.execute(
                    text(
                        """
                        UPDATE execution_attempts
                        SET
                            outcome = :outcome,
                            completed_at_utc =
                                :completed_at_utc,
                            error_type = :error_type,
                            error_message = :error_message
                        WHERE attempt_id = :attempt_id
                          AND outcome = :started
                        """
                    ),
                    {
                        "outcome": outcome,
                        "completed_at_utc": (
                            completed.isoformat()
                        ),
                        "error_type": error_type,
                        "error_message": error_message,
                        "attempt_id": attempt_id,
                        "started": (
                            ExecutionAttemptOutcome.STARTED
                        ),
                    },
                )

                if result.rowcount != 1:
                    raise (
                        InvalidExecutionAttemptStateError(
                            "Execution attempt changed "
                            "state before it could be "
                            "finalized."
                        )
                    )

        except InvalidExecutionAttemptStateError:
            raise

        except Exception as exc:
            raise ExecutionAttemptStorageError(
                "Failed to finalize execution attempt."
            ) from exc

        record = self.get_attempt(
            attempt_id
        )

        if record is None:
            raise ExecutionAttemptStorageError(
                "Finalized execution attempt could "
                "not be read back."
            )

        return record

    def get_attempt(
        self,
        attempt_id: str,
    ) -> ExecutionAttemptRecord | None:

        attempt_id = (
            self._normalize_required_text(
                attempt_id,
                "attempt_id",
            )
        )

        with self.engine.connect() as connection:

            row = connection.execute(
                text(
                    """
                    SELECT
                        attempt_id,
                        order_id,
                        execution_run_id,
                        execution_observed_at_utc,
                        outcome,
                        created_at_utc,
                        completed_at_utc,
                        error_type,
                        error_message
                    FROM execution_attempts
                    WHERE attempt_id = :attempt_id
                    """
                ),
                {
                    "attempt_id": attempt_id
                },
            ).mappings().first()

        if row is None:
            return None

        return self._row_to_record(
            row
        )

    def list_attempts_for_order(
        self,
        order_id: str,
    ) -> list[ExecutionAttemptRecord]:

        order_id = self._normalize_required_text(
            order_id,
            "order_id",
        )

        with self.engine.connect() as connection:

            rows = connection.execute(
                text(
                    """
                    SELECT
                        attempt_id,
                        order_id,
                        execution_run_id,
                        execution_observed_at_utc,
                        outcome,
                        created_at_utc,
                        completed_at_utc,
                        error_type,
                        error_message
                    FROM execution_attempts
                    WHERE order_id = :order_id
                    ORDER BY created_at_utc ASC
                    """
                ),
                {
                    "order_id": order_id
                },
            ).mappings().all()

        return [
            self._row_to_record(
                row
            )
            for row in rows
        ]

    def count_attempts(
        self,
    ) -> int:

        with self.engine.connect() as connection:

            value = connection.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM execution_attempts
                    """
                )
            ).scalar_one()

        return int(
            value
        )

    @staticmethod
    def _normalize_required_text(
        value,
        name: str,
    ) -> str:

        normalized = str(
            value
        ).strip()

        if not normalized:
            raise ValueError(
                f"{name} cannot be empty."
            )

        return normalized

    @staticmethod
    def _normalize_utc_datetime(
        value: datetime,
        name: str,
    ) -> datetime:

        if not isinstance(
            value,
            datetime,
        ):
            raise TypeError(
                f"{name} must be a datetime."
            )

        if value.tzinfo is None:
            raise ValueError(
                f"{name} must be timezone-aware."
            )

        return value.astimezone(
            timezone.utc
        )

    @staticmethod
    def _parse_datetime(
        value: str | None,
    ) -> datetime | None:

        if value is None:
            return None

        return datetime.fromisoformat(
            value
        )

    @classmethod
    def _row_to_record(
        cls,
        row,
    ) -> ExecutionAttemptRecord:

        return ExecutionAttemptRecord(
            attempt_id=row[
                "attempt_id"
            ],
            order_id=row[
                "order_id"
            ],
            execution_run_id=row[
                "execution_run_id"
            ],
            execution_observed_at_utc=(
                cls._parse_datetime(
                    row[
                        "execution_observed_at_utc"
                    ]
                )
            ),
            outcome=row[
                "outcome"
            ],
            created_at_utc=(
                cls._parse_datetime(
                    row[
                        "created_at_utc"
                    ]
                )
            ),
            completed_at_utc=(
                cls._parse_datetime(
                    row[
                        "completed_at_utc"
                    ]
                )
            ),
            error_type=row[
                "error_type"
            ],
            error_message=row[
                "error_message"
            ],
        )