
from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

from model2_config import (
    MODEL_2_ACCOUNT_ID,
    MODEL_2_VERSION,
    get_model2_paths,
)


DECISION_SESSION = date(2026, 9, 17)
EXPECTED_EXECUTION_SESSION = date(2026, 9, 18)
EXPECTED_ORDER_COUNT = 5


def inspect_orders() -> None:
    paths = get_model2_paths()
    database_path = Path(paths.model2_database).resolve()

    if database_path == Path(paths.model1_database).resolve():
        raise RuntimeError(
            "Model 2 and Model 1 database paths must differ."
        )

    if not database_path.is_file():
        raise RuntimeError("Model 2 database does not exist.")

    # mode=ro prevents this script from creating or
    # modifying the database.
    uri = database_path.as_uri() + "?mode=ro"

    with sqlite3.connect(uri, uri=True) as connection:
        connection.row_factory = sqlite3.Row

        accounts = connection.execute(
            """
            SELECT account_id, starting_cash
            FROM paper_accounts
            """
        ).fetchall()

        if (
            len(accounts) != 1
            or accounts[0]["account_id"]
            != MODEL_2_ACCOUNT_ID
        ):
            raise RuntimeError(
                "Unexpected Model 2 account configuration."
            )

        ledger = connection.execute(
            """
            SELECT
                run_id,
                status,
                orders_created,
                failed_tickers
            FROM model2_decision_runs
            WHERE decision_session = ?
              AND model_version = ?
            """,
            (
                DECISION_SESSION.isoformat(),
                MODEL_2_VERSION,
            ),
        ).fetchone()

        if ledger is None:
            raise RuntimeError(
                "No decision ledger record exists "
                "for the requested session."
            )

        orders = connection.execute(
            """
            SELECT
                o.order_id,
                o.ticker,
                o.side,
                o.quantity,
                o.status,
                o.execution_session,
                o.model_version,
                l.decision_run_id,
                (
                    SELECT COUNT(*)
                    FROM paper_fills AS f
                    WHERE f.order_id = o.order_id
                ) AS fill_count,
                (
                    SELECT COUNT(*)
                    FROM ingestion_runs AS i
                    WHERE i.run_id = l.decision_run_id
                ) AS decision_source_count
            FROM paper_orders AS o
            LEFT JOIN order_decision_lineage AS l
                ON l.order_id = o.order_id
            WHERE o.order_id LIKE ?
            ORDER BY o.ticker, o.order_id
            """,
            (
                f"{MODEL_2_VERSION}-"
                f"{DECISION_SESSION.isoformat()}-%",
            ),
        ).fetchall()

    print("Model 2 order inspection — READ ONLY")
    print("====================================")
    print(f"Database: {database_path}")
    print(f"Account: {accounts[0]['account_id']}")
    print(f"Decision session: {DECISION_SESSION}")
    print(f"Ledger run ID: {ledger['run_id']}")
    print(f"Ledger status: {ledger['status']}")
    print(f"Ledger orders created: {ledger['orders_created']}")
    print(f"Ledger failed tickers: {ledger['failed_tickers']}")
    print(f"Orders found: {len(orders)}")
    print()

    problems = []

    if ledger["status"] != "COMPLETED":
        problems.append("Decision ledger is not COMPLETED.")

    if ledger["orders_created"] != EXPECTED_ORDER_COUNT:
        problems.append("Ledger order count differs from expected.")

    if ledger["failed_tickers"] != 0:
        problems.append("Decision ledger reports ticker failures.")

    if len(orders) != EXPECTED_ORDER_COUNT:
        problems.append("Saved order count differs from expected.")

    for order in orders:
        print(
            f"{order['ticker']}: "
            f"{order['side']} {order['quantity']} | "
            f"{order['status']}"
        )
        print(f"  Order ID: {order['order_id']}")
        print(
            "  Execution session: "
            f"{order['execution_session']}"
        )
        print(
            f"  Model version: {order['model_version']}"
        )
        print(
            "  Decision-data run ID: "
            f"{order['decision_run_id']}"
        )
        print(f"  Existing fills: {order['fill_count']}")
        print()

        if order["status"] != "PENDING":
            problems.append(
                f"{order['order_id']}: not PENDING."
            )

        if (
            order["execution_session"]
            != EXPECTED_EXECUTION_SESSION.isoformat()
        ):
            problems.append(
                f"{order['order_id']}: unexpected "
                "execution session."
            )

        if order["model_version"] != MODEL_2_VERSION:
            problems.append(
                f"{order['order_id']}: wrong model version."
            )

        if (
            not order["decision_run_id"]
            or order["decision_source_count"] != 1
        ):
            problems.append(
                f"{order['order_id']}: missing or invalid "
                "decision-data lineage."
            )

        if order["fill_count"] != 0:
            problems.append(
                f"{order['order_id']}: a fill already exists."
            )

    if problems:
        print("INSPECTION RESULT: ATTENTION REQUIRED")
        for problem in problems:
            print(f"  - {problem}")
    else:
        print("INSPECTION RESULT: CHECKS PASSED")

    print("No database changes were made.")


if __name__ == "__main__":
    inspect_orders()