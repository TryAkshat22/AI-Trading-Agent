from __future__ import annotations

import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from model2_config import get_model2_paths


class Model2SchemaMigrationError(RuntimeError):
    """The one-time Model 2 schema migration could not proceed."""


EXECUTION_ATTEMPT_COLUMNS = (
    "attempt_id",
    "order_id",
    "execution_run_id",
    "execution_observed_at_utc",
    "outcome",
    "created_at_utc",
    "completed_at_utc",
    "error_type",
    "error_message",
)


OBSERVATION_LINEAGE_COLUMNS = (
    "execution_run_id",
    "source_database",
    "source_observation_id",
    "ticker",
    "provider",
    "execution_session",
    "bar_start_utc",
    "bar_end_utc",
    "retrieved_at_utc",
    "validated_at_utc",
    "price_field",
    "reference_price",
    "open_price",
    "high_price",
    "low_price",
    "close_price",
    "volume",
    "observation_model",
)


def _table_exists(
    connection: sqlite3.Connection,
    table_name: str,
) -> bool:
    return (
        connection.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table'
              AND name = ?
            """,
            (table_name,),
        ).fetchone()
        is not None
    )


def _columns(
    connection: sqlite3.Connection,
    table_name: str,
) -> tuple[str, ...]:
    return tuple(
        row[1]
        for row in connection.execute(
            f"PRAGMA table_info({table_name})"
        ).fetchall()
    )


def _foreign_keys(
    connection: sqlite3.Connection,
    table_name: str,
) -> list[tuple]:
    return connection.execute(
        f"PRAGMA foreign_key_list({table_name})"
    ).fetchall()


def _read_rows(
    connection: sqlite3.Connection,
    query: str,
) -> tuple[tuple, ...]:
    return tuple(
        connection.execute(query).fetchall()
    )


def _build_backup_path(
    database_path: Path,
) -> Path:
    timestamp = datetime.now(
        timezone.utc
    ).strftime("%Y%m%dT%H%M%SZ")

    return database_path.with_name(
        f"{database_path.stem}"
        f"_pre_execution_schema_{timestamp}"
        f"{database_path.suffix}"
    )


def migrate_model2_schema() -> Path:
    paths = get_model2_paths()

    model1_database = Path(
        paths.model1_database
    ).expanduser().resolve()

    model2_database = Path(
        paths.model2_database
    ).expanduser().resolve()

    observation_database = Path(
        paths.observation_database
    ).expanduser().resolve()

    print()
    print("MODEL 2 EXECUTION SCHEMA MIGRATION")
    print("==================================")
    print()

    print(f"Model 1 DB:     {model1_database}")
    print(f"Model 2 DB:     {model2_database}")
    print(f"Observation DB: {observation_database}")
    print()

    # ---------------------------------------------------------
    # Path safety
    # ---------------------------------------------------------

    if model2_database == model1_database:
        raise Model2SchemaMigrationError(
            "Refusing migration because Model 2 "
            "resolves to the Model 1 database."
        )

    if model2_database == observation_database:
        raise Model2SchemaMigrationError(
            "Refusing migration because Model 2 "
            "resolves to the observation database."
        )

    if not model2_database.is_file():
        raise Model2SchemaMigrationError(
            "Model 2 database does not exist."
        )

    if not model1_database.is_file():
        raise Model2SchemaMigrationError(
            "Model 1 database does not exist."
        )

    if not observation_database.is_file():
        raise Model2SchemaMigrationError(
            "Observation database does not exist."
        )

    # ---------------------------------------------------------
    # Read current Model 2 state before touching anything
    # ---------------------------------------------------------

    uri = model2_database.as_uri() + "?mode=rw"

    connection = sqlite3.connect(
        uri,
        uri=True,
        timeout=15,
        isolation_level=None,
    )

    backup_path: Path | None = None

    try:
        connection.execute(
            "PRAGMA foreign_keys = ON"
        )
        connection.execute(
            "PRAGMA busy_timeout = 15000"
        )

        required_existing = (
            "paper_accounts",
            "paper_orders",
            "paper_fills",
            "order_rejections",
            "ingestion_runs",
            "fill_execution_lineage",
        )

        for table_name in required_existing:
            if not _table_exists(
                connection,
                table_name,
            ):
                raise Model2SchemaMigrationError(
                    "Required existing table is missing: "
                    f"{table_name}"
                )

        account_rows = _read_rows(
            connection,
            """
            SELECT
                account_id,
                starting_cash,
                created_at_utc
            FROM paper_accounts
            ORDER BY account_id
            """,
        )

        if (
            len(account_rows) != 1
            or account_rows[0][0] != "model2-paper"
        ):
            raise Model2SchemaMigrationError(
                "Unexpected Model 2 account configuration."
            )

        orders_before = _read_rows(
            connection,
            """
            SELECT *
            FROM paper_orders
            ORDER BY order_id
            """,
        )

        fills_before = _read_rows(
            connection,
            """
            SELECT *
            FROM paper_fills
            ORDER BY fill_id
            """,
        )

        rejections_before = _read_rows(
            connection,
            """
            SELECT *
            FROM order_rejections
            ORDER BY order_id
            """,
        )

        ingestion_before = _read_rows(
            connection,
            """
            SELECT *
            FROM ingestion_runs
            ORDER BY run_id
            """,
        )

        fill_lineage_before = _read_rows(
            connection,
            """
            SELECT *
            FROM fill_execution_lineage
            ORDER BY fill_id
            """,
        )

        pending_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM paper_orders
            WHERE status = 'PENDING'
            """
        ).fetchone()[0]

        fill_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM paper_fills
            """
        ).fetchone()[0]

        print("PRE-MIGRATION STATE")
        print("-------------------")
        print(
            f"Orders:          {len(orders_before)}"
        )
        print(
            f"Pending orders:  {pending_count}"
        )
        print(
            f"Fills:           {fill_count}"
        )
        print(
            f"Rejections:      {len(rejections_before)}"
        )
        print()

        # We deliberately migrate while there is no
        # pending execution state.
        if pending_count != 0:
            raise Model2SchemaMigrationError(
                "Refusing migration while PENDING "
                "orders exist."
            )

        if fill_count != 0:
            raise Model2SchemaMigrationError(
                "Refusing this initial migration while "
                "paper fills already exist."
            )

        execution_attempts_exists = (
            _table_exists(
                connection,
                "execution_attempts",
            )
        )

        observation_lineage_exists = (
            _table_exists(
                connection,
                "model2_execution_observation_lineage",
            )
        )

        print("TARGET TABLES")
        print("-------------")
        print(
            "execution_attempts: "
            + (
                "already present"
                if execution_attempts_exists
                else "missing"
            )
        )
        print(
            "model2_execution_observation_lineage: "
            + (
                "already present"
                if observation_lineage_exists
                else "missing"
            )
        )
        print()

        # If either table unexpectedly already exists,
        # verify it before doing anything else.
        if execution_attempts_exists:
            existing_columns = _columns(
                connection,
                "execution_attempts",
            )

            if existing_columns != EXECUTION_ATTEMPT_COLUMNS:
                raise Model2SchemaMigrationError(
                    "Existing execution_attempts table "
                    "has an unexpected schema."
                )

        if observation_lineage_exists:
            existing_columns = _columns(
                connection,
                "model2_execution_observation_lineage",
            )

            if (
                existing_columns
                != OBSERVATION_LINEAGE_COLUMNS
            ):
                raise Model2SchemaMigrationError(
                    "Existing execution-observation "
                    "lineage table has an unexpected schema."
                )

        if (
            execution_attempts_exists
            and observation_lineage_exists
        ):
            print(
                "Both target tables already exist "
                "with the expected columns."
            )
            print(
                "No migration is necessary."
            )

            return model2_database

        # -----------------------------------------------------
        # Backup BEFORE schema mutation
        # -----------------------------------------------------

        backup_path = _build_backup_path(
            model2_database
        )

        if backup_path.exists():
            raise Model2SchemaMigrationError(
                "Generated backup path already exists."
            )

        connection.close()

        shutil.copy2(
            model2_database,
            backup_path,
        )

        if not backup_path.is_file():
            raise Model2SchemaMigrationError(
                "Backup could not be verified."
            )

        if (
            backup_path.stat().st_size
            != model2_database.stat().st_size
        ):
            raise Model2SchemaMigrationError(
                "Backup file size differs from "
                "the original database."
            )

        print("BACKUP")
        print("------")
        print(
            f"Created: {backup_path}"
        )
        print()

        # Reopen only after the backup is complete.
        connection = sqlite3.connect(
            uri,
            uri=True,
            timeout=15,
            isolation_level=None,
        )

        connection.execute(
            "PRAGMA foreign_keys = ON"
        )
        connection.execute(
            "PRAGMA busy_timeout = 15000"
        )

        # -----------------------------------------------------
        # One atomic schema transaction
        # -----------------------------------------------------

        connection.execute(
            "BEGIN IMMEDIATE"
        )

        connection.execute(
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

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS
            model2_execution_observation_lineage
            (
                execution_run_id TEXT PRIMARY KEY,

                source_database TEXT NOT NULL,

                source_observation_id INTEGER NOT NULL,

                ticker TEXT NOT NULL,

                provider TEXT NOT NULL,

                execution_session TEXT NOT NULL,

                bar_start_utc TEXT NOT NULL,

                bar_end_utc TEXT NOT NULL,

                retrieved_at_utc TEXT NOT NULL,

                validated_at_utc TEXT NOT NULL,

                price_field TEXT NOT NULL,

                reference_price REAL NOT NULL,

                open_price REAL NOT NULL,

                high_price REAL NOT NULL,

                low_price REAL NOT NULL,

                close_price REAL NOT NULL,

                volume REAL NOT NULL,

                observation_model TEXT NOT NULL,

                FOREIGN KEY (execution_run_id)
                    REFERENCES ingestion_runs(run_id),

                UNIQUE (
                    source_database,
                    source_observation_id
                )
            )
            """
        )

        # -----------------------------------------------------
        # Verify table columns BEFORE committing
        # -----------------------------------------------------

        attempts_columns = _columns(
            connection,
            "execution_attempts",
        )

        if (
            attempts_columns
            != EXECUTION_ATTEMPT_COLUMNS
        ):
            raise Model2SchemaMigrationError(
                "execution_attempts schema verification "
                "failed."
            )

        lineage_columns = _columns(
            connection,
            "model2_execution_observation_lineage",
        )

        if (
            lineage_columns
            != OBSERVATION_LINEAGE_COLUMNS
        ):
            raise Model2SchemaMigrationError(
                "Execution-observation lineage schema "
                "verification failed."
            )

        # -----------------------------------------------------
        # Verify execution_attempts foreign keys
        # -----------------------------------------------------

        attempts_foreign_keys = _foreign_keys(
            connection,
            "execution_attempts",
        )

        attempts_fk_targets = {
            (
                row[2],
                row[3],
                row[4],
            )
            for row in attempts_foreign_keys
        }

        required_attempt_fks = {
            (
                "paper_orders",
                "order_id",
                "order_id",
            ),
            (
                "ingestion_runs",
                "execution_run_id",
                "run_id",
            ),
        }

        if not required_attempt_fks.issubset(
            attempts_fk_targets
        ):
            raise Model2SchemaMigrationError(
                "execution_attempts foreign-key "
                "verification failed."
            )

        lineage_foreign_keys = _foreign_keys(
            connection,
            "model2_execution_observation_lineage",
        )

        lineage_fk_targets = {
            (
                row[2],
                row[3],
                row[4],
            )
            for row in lineage_foreign_keys
        }

        if (
            (
                "ingestion_runs",
                "execution_run_id",
                "run_id",
            )
            not in lineage_fk_targets
        ):
            raise Model2SchemaMigrationError(
                "Execution-observation lineage "
                "foreign-key verification failed."
            )

        # Both tables must begin empty.
        attempts_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM execution_attempts
            """
        ).fetchone()[0]

        lineage_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM model2_execution_observation_lineage
            """
        ).fetchone()[0]

        if attempts_count != 0:
            raise Model2SchemaMigrationError(
                "execution_attempts unexpectedly "
                "contains records."
            )

        if lineage_count != 0:
            raise Model2SchemaMigrationError(
                "Execution-observation lineage "
                "unexpectedly contains records."
            )

        # -----------------------------------------------------
        # Ensure existing trading history was untouched
        # -----------------------------------------------------

        orders_after = _read_rows(
            connection,
            """
            SELECT *
            FROM paper_orders
            ORDER BY order_id
            """,
        )

        fills_after = _read_rows(
            connection,
            """
            SELECT *
            FROM paper_fills
            ORDER BY fill_id
            """,
        )

        rejections_after = _read_rows(
            connection,
            """
            SELECT *
            FROM order_rejections
            ORDER BY order_id
            """,
        )

        ingestion_after = _read_rows(
            connection,
            """
            SELECT *
            FROM ingestion_runs
            ORDER BY run_id
            """,
        )

        fill_lineage_after = _read_rows(
            connection,
            """
            SELECT *
            FROM fill_execution_lineage
            ORDER BY fill_id
            """,
        )

        if orders_after != orders_before:
            raise Model2SchemaMigrationError(
                "paper_orders changed during migration."
            )

        if fills_after != fills_before:
            raise Model2SchemaMigrationError(
                "paper_fills changed during migration."
            )

        if rejections_after != rejections_before:
            raise Model2SchemaMigrationError(
                "order_rejections changed during migration."
            )

        if ingestion_after != ingestion_before:
            raise Model2SchemaMigrationError(
                "ingestion_runs changed during migration."
            )

        if (
            fill_lineage_after
            != fill_lineage_before
        ):
            raise Model2SchemaMigrationError(
                "fill_execution_lineage changed "
                "during migration."
            )

        connection.execute(
            "COMMIT"
        )

        # -----------------------------------------------------
        # Final post-commit verification
        # -----------------------------------------------------

        if not _table_exists(
            connection,
            "execution_attempts",
        ):
            raise Model2SchemaMigrationError(
                "execution_attempts missing "
                "after commit."
            )

        if not _table_exists(
            connection,
            "model2_execution_observation_lineage",
        ):
            raise Model2SchemaMigrationError(
                "Execution-observation lineage "
                "missing after commit."
            )

        print("MIGRATION RESULT")
        print("----------------")
        print(
            "execution_attempts: PRESENT"
        )
        print(
            "model2_execution_observation_lineage: "
            "PRESENT"
        )
        print(
            "Execution attempts rows: 0"
        )
        print(
            "Observation lineage rows: 0"
        )
        print()
        print(
            "Existing orders unchanged: YES"
        )
        print(
            "Existing fills unchanged: YES"
        )
        print(
            "Existing rejections unchanged: YES"
        )
        print(
            "Existing ingestion runs unchanged: YES"
        )
        print(
            "Existing fill lineage unchanged: YES"
        )
        print()
        print(
            "MODEL 2 EXECUTION SCHEMA MIGRATION: PASS"
        )
        print()
        print(
            "No orders were created, executed, "
            "rejected, or modified."
        )

        return backup_path

    except BaseException:
        try:
            if (
                connection is not None
                and connection.in_transaction
            ):
                connection.execute(
                    "ROLLBACK"
                )
        except Exception:
            pass

        raise

    finally:
        try:
            connection.close()
        except Exception:
            pass


def main() -> int:
    try:
        backup_path = migrate_model2_schema()

        print()

        if (
            backup_path.name
            != "trading_agent_model2.db"
        ):
            print(
                "Backup retained at:"
            )
            print(
                f"  {backup_path}"
            )

        return 0

    except Exception as exc:
        print()
        print(
            "MODEL 2 SCHEMA MIGRATION: BLOCKED",
            file=sys.stderr,
        )
        print(
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        print(
            "If a transaction had started, "
            "it was rolled back.",
            file=sys.stderr,
        )

        return 1


if __name__ == "__main__":
    raise SystemExit(main())