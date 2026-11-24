from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

from model2_config import (
    MODEL_2_ACCOUNT_ID,
    MODEL_2_VERSION,
    get_model2_paths,
)


REQUIRED_EXECUTION_TABLES = (
    "paper_accounts",
    "paper_orders",
    "paper_fills",
    "order_rejections",
    "execution_attempts",
    "ingestion_runs",
    "model2_execution_observation_lineage",
    "fill_execution_lineage",
)


class Model2InspectionError(RuntimeError):
    """Read-only Model 2 inspection could not be completed."""


def table_exists(
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


def column_names(
    connection: sqlite3.Connection,
    table_name: str,
) -> tuple[str, ...]:
    rows = connection.execute(
        f"PRAGMA table_info({table_name})"
    ).fetchall()

    return tuple(
        row[1]
        for row in rows
    )


def scalar(
    connection: sqlite3.Connection,
    query: str,
    parameters=(),
):
    row = connection.execute(
        query,
        parameters,
    ).fetchone()

    if row is None:
        return None

    return row[0]


def inspect_model2_database() -> int:
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
    print("MODEL 2 LIVE DATABASE INSPECTION")
    print("================================")
    print("READ ONLY")
    print()

    print(f"Model 1 DB:     {model1_database}")
    print(f"Model 2 DB:     {model2_database}")
    print(f"Observation DB: {observation_database}")
    print()

    if model2_database == model1_database:
        raise Model2InspectionError(
            "BLOCKED: Model 2 database resolves "
            "to the Model 1 database."
        )

    if model2_database == observation_database:
        raise Model2InspectionError(
            "BLOCKED: Model 2 trading database resolves "
            "to the observation database."
        )

    if not model2_database.is_file():
        raise Model2InspectionError(
            "Model 2 database file does not exist."
        )

    if not observation_database.is_file():
        raise Model2InspectionError(
            "Observation database file does not exist."
        )

    connection = sqlite3.connect(
        model2_database.as_uri() + "?mode=ro",
        uri=True,
        timeout=10,
    )

    try:
        connection.execute(
            "PRAGMA query_only = ON"
        )

        print("DATABASE ISOLATION")
        print("------------------")
        print("Model 1 separate:       YES")
        print("Observation DB separate: YES")
        print()

        print("REQUIRED TABLES")
        print("---------------")

        missing_tables = []

        for table_name in REQUIRED_EXECUTION_TABLES:
            exists = table_exists(
                connection,
                table_name,
            )

            status = (
                "PRESENT"
                if exists
                else "MISSING"
            )

            print(
                f"{table_name:<42} {status}"
            )

            if not exists:
                missing_tables.append(
                    table_name
                )

        print()

        if not table_exists(
            connection,
            "paper_accounts",
        ):
            raise Model2InspectionError(
                "paper_accounts is missing; "
                "cannot continue account inspection."
            )

        print("ACCOUNT")
        print("-------")

        account_rows = connection.execute(
            """
            SELECT *
            FROM paper_accounts
            """
        ).fetchall()

        account_columns = column_names(
            connection,
            "paper_accounts",
        )

        print(
            "Columns: "
            + ", ".join(account_columns)
        )

        print(
            f"Account row count: "
            f"{len(account_rows)}"
        )

        for row in account_rows:
            print(f"  {row}")

        print()

        account_id_index = (
            account_columns.index("account_id")
            if "account_id" in account_columns
            else None
        )

        if account_id_index is None:
            print(
                "ACCOUNT CHECK: BLOCKED "
                "(account_id column missing)"
            )

        else:
            account_ids = [
                row[account_id_index]
                for row in account_rows
            ]

            if account_ids == [
                MODEL_2_ACCOUNT_ID
            ]:
                print(
                    "ACCOUNT CHECK: PASS"
                )
            else:
                print(
                    "ACCOUNT CHECK: BLOCKED"
                )
                print(
                    "Expected exactly: "
                    f"{MODEL_2_ACCOUNT_ID}"
                )
                print(
                    "Found: "
                    f"{account_ids}"
                )

        print()

        if table_exists(
            connection,
            "paper_orders",
        ):
            print("ORDER SUMMARY")
            print("-------------")

            total_orders = scalar(
                connection,
                """
                SELECT COUNT(*)
                FROM paper_orders
                """,
            )

            print(
                f"Total orders: {total_orders}"
            )

            rows = connection.execute(
                """
                SELECT
                    status,
                    COUNT(*)
                FROM paper_orders
                GROUP BY status
                ORDER BY status
                """
            ).fetchall()

            for status, count in rows:
                print(
                    f"  {status}: {count}"
                )

            print()

            print(
                "ORDERS BY SESSION / MODEL"
            )
            print(
                "-------------------------"
            )

            rows = connection.execute(
                """
                SELECT
                    execution_session,
                    model_version,
                    status,
                    COUNT(*)
                FROM paper_orders
                GROUP BY
                    execution_session,
                    model_version,
                    status
                ORDER BY
                    execution_session,
                    model_version,
                    status
                """
            ).fetchall()

            for row in rows:
                print(f"  {row}")

            print()

            pending_rows = connection.execute(
                """
                SELECT
                    order_id,
                    ticker,
                    side,
                    quantity,
                    execution_session,
                    status,
                    model_version
                FROM paper_orders
                WHERE status = 'PENDING'
                ORDER BY
                    execution_session,
                    ticker,
                    order_id
                """
            ).fetchall()

            print(
                f"Pending orders: "
                f"{len(pending_rows)}"
            )

            for row in pending_rows:
                print(f"  {row}")

            print()

            model2_count = scalar(
                connection,
                """
                SELECT COUNT(*)
                FROM paper_orders
                WHERE model_version = ?
                """,
                (MODEL_2_VERSION,),
            )

            foreign_model_count = scalar(
                connection,
                """
                SELECT COUNT(*)
                FROM paper_orders
                WHERE model_version <> ?
                   OR model_version IS NULL
                """,
                (MODEL_2_VERSION,),
            )

            print(
                f"Model 2 version orders: "
                f"{model2_count}"
            )

            print(
                "Unexpected model-version orders: "
                f"{foreign_model_count}"
            )

            print()

        if table_exists(
            connection,
            "paper_fills",
        ):
            fill_count = scalar(
                connection,
                """
                SELECT COUNT(*)
                FROM paper_fills
                """,
            )

            print("FILL SUMMARY")
            print("------------")
            print(
                f"Total fills: {fill_count}"
            )

            rows = connection.execute(
                """
                SELECT
                    f.fill_id,
                    f.order_id,
                    f.ticker,
                    f.side,
                    f.quantity,
                    f.execution_session,
                    f.reference_price,
                    f.fill_price,
                    f.created_at_utc
                FROM paper_fills AS f
                ORDER BY
                    f.execution_session,
                    f.created_at_utc,
                    f.fill_id
                """
            ).fetchall()

            for row in rows:
                print(f"  {row}")

            print()

        if table_exists(
            connection,
            "order_rejections",
        ):
            rejection_count = scalar(
                connection,
                """
                SELECT COUNT(*)
                FROM order_rejections
                """,
            )

            print("REJECTION SUMMARY")
            print("-----------------")
            print(
                f"Total rejection records: "
                f"{rejection_count}"
            )

            rows = connection.execute(
                """
                SELECT *
                FROM order_rejections
                ORDER BY rowid
                """
            ).fetchall()

            for row in rows:
                print(f"  {row}")

            print()

        if table_exists(
            connection,
            "execution_attempts",
        ):
            attempt_count = scalar(
                connection,
                """
                SELECT COUNT(*)
                FROM execution_attempts
                """,
            )

            print("EXECUTION ATTEMPTS")
            print("------------------")
            print(
                f"Total attempts: "
                f"{attempt_count}"
            )

            rows = connection.execute(
                """
                SELECT *
                FROM execution_attempts
                ORDER BY rowid
                """
            ).fetchall()

            for row in rows:
                print(f"  {row}")

            print()

        else:
            print("EXECUTION ATTEMPTS")
            print("------------------")
            print(
                "execution_attempts table is MISSING."
            )
            print()

        if table_exists(
            connection,
            "fill_execution_lineage",
        ):
            lineage_count = scalar(
                connection,
                """
                SELECT COUNT(*)
                FROM fill_execution_lineage
                """,
            )

            print("FILL EXECUTION LINEAGE")
            print("----------------------")
            print(
                f"Rows: {lineage_count}"
            )

            rows = connection.execute(
                """
                SELECT *
                FROM fill_execution_lineage
                ORDER BY rowid
                """
            ).fetchall()

            for row in rows:
                print(f"  {row}")

            print()

        if table_exists(
            connection,
            "model2_execution_observation_lineage",
        ):
            observation_lineage_count = scalar(
                connection,
                """
                SELECT COUNT(*)
                FROM model2_execution_observation_lineage
                """,
            )

            print(
                "EXECUTION OBSERVATION LINEAGE"
            )
            print(
                "-----------------------------"
            )
            print(
                f"Rows: "
                f"{observation_lineage_count}"
            )
            print()

        print("CONSISTENCY CHECKS")
        print("------------------")

        blockers = []

        if missing_tables:
            blockers.append(
                "Missing required tables: "
                + ", ".join(
                    missing_tables
                )
            )

        if table_exists(
            connection,
            "paper_orders",
        ):
            pending_count = scalar(
                connection,
                """
                SELECT COUNT(*)
                FROM paper_orders
                WHERE status = 'PENDING'
                """,
            )

            print(
                "Pending orders currently present: "
                f"{pending_count}"
            )

            if pending_count != 0:
                blockers.append(
                    "Existing PENDING orders require "
                    "manual review before creating a "
                    "new controlled trial order."
                )

            filled_without_fill = scalar(
                connection,
                """
                SELECT COUNT(*)
                FROM paper_orders AS o
                WHERE o.status = 'FILLED'
                  AND (
                      SELECT COUNT(*)
                      FROM paper_fills AS f
                      WHERE f.order_id = o.order_id
                  ) <> 1
                """,
            )

            print(
                "FILLED orders without exactly "
                f"one fill: {filled_without_fill}"
            )

            if filled_without_fill != 0:
                blockers.append(
                    "At least one FILLED order does not "
                    "have exactly one fill."
                )

            pending_with_fill = scalar(
                connection,
                """
                SELECT COUNT(*)
                FROM paper_orders AS o
                WHERE o.status = 'PENDING'
                  AND EXISTS (
                      SELECT 1
                      FROM paper_fills AS f
                      WHERE f.order_id = o.order_id
                  )
                """,
            )

            print(
                "PENDING orders with fills: "
                f"{pending_with_fill}"
            )

            if pending_with_fill != 0:
                blockers.append(
                    "At least one PENDING order "
                    "already has a fill."
                )

        if (
            table_exists(
                connection,
                "paper_fills",
            )
            and table_exists(
                connection,
                "paper_orders",
            )
        ):
            orphan_fills = scalar(
                connection,
                """
                SELECT COUNT(*)
                FROM paper_fills AS f
                LEFT JOIN paper_orders AS o
                  ON o.order_id = f.order_id
                WHERE o.order_id IS NULL
                """,
            )

            print(
                f"Orphan fills: {orphan_fills}"
            )

            if orphan_fills != 0:
                blockers.append(
                    "Orphan fill records exist."
                )

        if (
            table_exists(
                connection,
                "fill_execution_lineage",
            )
            and table_exists(
                connection,
                "paper_fills",
            )
        ):
            orphan_lineage = scalar(
                connection,
                """
                SELECT COUNT(*)
                FROM fill_execution_lineage AS l
                LEFT JOIN paper_fills AS f
                  ON f.fill_id = l.fill_id
                WHERE f.fill_id IS NULL
                """,
            )

            print(
                "Orphan fill-lineage records: "
                f"{orphan_lineage}"
            )

            if orphan_lineage != 0:
                blockers.append(
                    "Orphan fill-execution lineage "
                    "records exist."
                )

        print()

        print("FINAL RESULT")
        print("------------")

        if blockers:
            print(
                "MODEL 2 CONTROLLED TRIAL: BLOCKED"
            )
            print()

            for blocker in blockers:
                print(
                    f"  - {blocker}"
                )

            print()
            print(
                "No database changes were made."
            )

            return 1

        print(
            "MODEL 2 DATABASE INSPECTION: PASS"
        )
        print()
        print(
            "No schema or consistency blocker "
            "was detected by this read-only check."
        )
        print()
        print(
            "This does NOT execute or authorize "
            "a paper trade."
        )

        return 0

    finally:
        connection.close()


def main() -> int:
    try:
        return inspect_model2_database()

    except Exception as exc:
        print()
        print(
            "MODEL 2 LIVE INSPECTION: BLOCKED",
            file=sys.stderr,
        )
        print(
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        print(
            "No database changes were made.",
            file=sys.stderr,
        )

        return 1


if __name__ == "__main__":
    raise SystemExit(main())