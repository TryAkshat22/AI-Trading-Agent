
from __future__ import annotations

import sqlite3
import sys
from datetime import date, datetime, time, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from model2_config import (
    MODEL_2_ACCOUNT_ID,
    MODEL_2_VERSION,
    get_model2_paths,
)


SESSION = date(2026, 9, 18)

EXPECTED_ORDERS = {
    "AAPL": 2,
    "GOOGL": 2,
    "META": 1,
    "MSFT": 2,
    "NVDA": 4,
}

NEW_YORK = ZoneInfo("America/New_York")


def table_exists(
    connection: sqlite3.Connection,
    name: str,
) -> bool:
    return (
        connection.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table'
              AND name = ?
            """,
            (name,),
        ).fetchone()
        is not None
    )


def main() -> int:
    paths = get_model2_paths()

    model1_db = Path(paths.model1_database).resolve()
    model2_db = Path(paths.model2_database).resolve()
    observation_db = Path(
        paths.observation_database
    ).resolve()

    if model2_db in {model1_db, observation_db}:
        print(
            "BLOCKED: Model 2 database is not separate."
        )
        return 1

    if not model2_db.is_file():
        print(
            "BLOCKED: Model 2 database does not exist."
        )
        return 1

    now_et = datetime.now(
        timezone.utc
    ).astimezone(NEW_YORK)

    cutoff_et = datetime.combine(
        SESSION,
        time(10, 30),
        tzinfo=NEW_YORK,
    )

    print("Model 2 expiry inspection — READ ONLY")
    print("=====================================")
    print(f"Database: {model2_db}")
    print(f"Inspection time: {now_et.isoformat()}")
    print(f"Execution session: {SESSION}")
    print(f"Execution cutoff: {cutoff_et.isoformat()}")
    print()

    try:
        with sqlite3.connect(
            model2_db.as_uri() + "?mode=ro",
            uri=True,
            timeout=10,
        ) as connection:
            connection.execute(
                "PRAGMA query_only = ON"
            )

            # The attempts table is optional because
            # it has not been initialized in the live
            # Model 2 database.
            required_tables = (
                "paper_accounts",
                "paper_orders",
                "paper_fills",
                "order_rejections",
            )

            missing = [
                name
                for name in required_tables
                if not table_exists(connection, name)
            ]

            if missing:
                print(
                    "INSPECTION INCOMPLETE: "
                    "Missing table(s): "
                    + ", ".join(missing)
                )
                print(
                    "No database changes were made."
                )
                return 1

            attempts_available = table_exists(
                connection,
                "execution_attempts",
            )

            accounts = connection.execute(
                """
                SELECT account_id
                FROM paper_accounts
                """
            ).fetchall()

            if accounts != [(MODEL_2_ACCOUNT_ID,)]:
                print(
                    "BLOCKED: Unexpected account "
                    f"configuration: {accounts}"
                )
                print(
                    "No database changes were made."
                )
                return 1

            rows = connection.execute(
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
                WHERE execution_session = ?
                ORDER BY ticker, order_id
                """,
                (SESSION.isoformat(),),
            ).fetchall()

            print(
                "Orders scheduled for this session: "
                f"{len(rows)}"
            )

            if not attempts_available:
                print(
                    "Execution attempt history: "
                    "UNAVAILABLE (table does not exist)"
                )

            seen_expected = set()
            attention_required = False

            for (
                order_id,
                ticker,
                side,
                quantity,
                execution_session,
                status,
                model_version,
            ) in rows:
                fills = connection.execute(
                    """
                    SELECT
                        fill_id,
                        execution_session,
                        reference_price,
                        fill_price
                    FROM paper_fills
                    WHERE order_id = ?
                    ORDER BY fill_id
                    """,
                    (order_id,),
                ).fetchall()

                if attempts_available:
                    attempts = connection.execute(
                        """
                        SELECT
                            attempt_id,
                            outcome,
                            execution_run_id,
                            created_at_utc,
                            completed_at_utc
                        FROM execution_attempts
                        WHERE order_id = ?
                        ORDER BY
                            created_at_utc,
                            attempt_id
                        """,
                        (order_id,),
                    ).fetchall()

                    attempt_count_label = str(
                        len(attempts)
                    )
                else:
                    attempts = []
                    attempt_count_label = (
                        "UNAVAILABLE "
                        "(table does not exist)"
                    )

                rejection = connection.execute(
                    """
                    SELECT
                        rejection_code,
                        rejection_reason,
                        rejected_at_utc
                    FROM order_rejections
                    WHERE order_id = ?
                    """,
                    (order_id,),
                ).fetchone()

                expected_id = (
                    f"{MODEL_2_VERSION}"
                    f"-2026-09-17-{ticker}"
                )

                expected = (
                    ticker in EXPECTED_ORDERS
                    and order_id == expected_id
                    and quantity == EXPECTED_ORDERS[ticker]
                    and side == "BUY"
                    and model_version == MODEL_2_VERSION
                )

                if expected:
                    seen_expected.add(ticker)
                else:
                    attention_required = True

                print()
                print(
                    f"{ticker}: {side} {quantity} "
                    f"| {status}"
                )
                print(f"  Order ID: {order_id}")
                print(
                    f"  Expected order: {expected}"
                )
                print(
                    f"  Execution session: "
                    f"{execution_session}"
                )
                print(
                    f"  Model version: {model_version}"
                )
                print(
                    f"  Fill count: {len(fills)}"
                )
                print(
                    "  Execution attempt count: "
                    f"{attempt_count_label}"
                )

                for fill in fills:
                    print(
                        "  FILL: "
                        f"id={fill[0]}, "
                        f"session={fill[1]}, "
                        f"reference={fill[2]}, "
                        f"price={fill[3]}"
                    )

                for attempt in attempts:
                    print(
                        "  ATTEMPT: "
                        f"id={attempt[0]}, "
                        f"outcome={attempt[1]}, "
                        f"run={attempt[2]}"
                    )
                    print(
                        f"    Created: {attempt[3]}"
                    )
                    print(
                        f"    Completed: {attempt[4]}"
                    )

                if rejection is not None:
                    print(
                        "  REJECTION: "
                        f"{rejection[0]} — "
                        f"{rejection[1]}"
                    )
                    print(
                        "    Rejected: "
                        f"{rejection[2]}"
                    )

                if (
                    status == "PENDING"
                    and now_et >= cutoff_et
                ):
                    print(
                        "  TIMING: Past execution "
                        "cutoff; must not be filled."
                    )
                elif status == "PENDING":
                    print(
                        "  TIMING: Pending; execution "
                        "is not authorized by "
                        "this inspection."
                    )

                if status == "PENDING" and fills:
                    attention_required = True
                    print(
                        "  WARNING: Pending order "
                        "has a fill."
                    )

                if (
                    status == "FILLED"
                    and len(fills) != 1
                ):
                    attention_required = True
                    print(
                        "  WARNING: Filled order "
                        "does not have exactly "
                        "one fill."
                    )

                if (
                    status == "FILLED"
                    and rejection is not None
                ):
                    attention_required = True
                    print(
                        "  WARNING: Filled order "
                        "also has a rejection."
                    )

                if (
                    status == "REJECTED"
                    and fills
                ):
                    attention_required = True
                    print(
                        "  WARNING: Rejected order "
                        "has a fill."
                    )

            missing_expected = (
                set(EXPECTED_ORDERS)
                - seen_expected
            )

            if missing_expected:
                attention_required = True
                print()
                print(
                    "Missing expected orders: "
                    + ", ".join(
                        sorted(missing_expected)
                    )
                )

            total_fills = connection.execute(
                """
                SELECT COUNT(*)
                FROM paper_fills
                """
            ).fetchone()[0]

            if attempts_available:
                total_attempts = connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM execution_attempts
                    """
                ).fetchone()[0]

                attempts_label = str(
                    total_attempts
                )
            else:
                attempts_label = (
                    "UNAVAILABLE "
                    "(table does not exist)"
                )

            print()
            print(
                f"Total Model 2 fills: {total_fills}"
            )
            print(
                "Total Model 2 execution attempts: "
                f"{attempts_label}"
            )
            print()

            if attention_required:
                print(
                    "INSPECTION RESULT: "
                    "ATTENTION REQUIRED"
                )
            else:
                print(
                    "INSPECTION RESULT: "
                    "Expected order identities verified"
                )

            print(
                "No database changes were made."
            )

            return (
                1
                if attention_required
                else 0
            )

    except sqlite3.Error as exc:
        print(
            f"INSPECTION FAILED: {exc}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())