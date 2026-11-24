from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from model2_config import (
    MODEL_2_ACCOUNT_ID,
    MODEL_2_VERSION,
    get_model2_paths,
)


REJECTION_CODE = "EXECUTION_WINDOW_EXPIRED"
CONFIRMATION_TEXT = "EXPIRE-MODEL2-ORDERS"

NEW_YORK = ZoneInfo("America/New_York")


class ExpiryBlocked(RuntimeError):
    """An order-expiry safety check failed."""


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


def verify_database(
    connection: sqlite3.Connection,
    *,
    execution_session: date,
    now_et: datetime,
) -> list[tuple[str, str, str, int]]:
    """
    Verify all stale PENDING Model 2 orders for one
    execution session.

    Returns:
        (order_id, ticker, side, quantity)

    This function never writes anything.
    """

    if execution_session >= now_et.date():
        raise ExpiryBlocked(
            "Only a past execution session may be expired."
        )

    required_tables = (
        "paper_accounts",
        "paper_orders",
        "paper_fills",
        "order_rejections",
        "execution_attempts",
    )

    missing = [
        name
        for name in required_tables
        if not table_exists(connection, name)
    ]

    if missing:
        raise ExpiryBlocked(
            "Required table(s) missing: "
            + ", ".join(missing)
        )

    accounts = connection.execute(
        """
        SELECT account_id
        FROM paper_accounts
        """
    ).fetchall()

    if accounts != [(MODEL_2_ACCOUNT_ID,)]:
        raise ExpiryBlocked(
            "Unexpected Model 2 account configuration."
        )

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
          AND model_version = ?
          AND status = 'PENDING'
        ORDER BY ticker, order_id
        """,
        (
            execution_session.isoformat(),
            MODEL_2_VERSION,
        ),
    ).fetchall()

    if not rows:
        raise ExpiryBlocked(
            "No stale PENDING Model 2 orders were found "
            "for the requested execution session."
        )

    verified = []

    for (
        order_id,
        ticker,
        side,
        quantity,
        stored_session,
        status,
        model_version,
    ) in rows:

        if (
            not order_id
            or not ticker
            or side not in {"BUY", "SELL"}
            or not isinstance(quantity, int)
            or quantity <= 0
            or stored_session
            != execution_session.isoformat()
            or status != "PENDING"
            or model_version != MODEL_2_VERSION
        ):
            raise ExpiryBlocked(
                "Order identity or state is invalid: "
                f"{order_id}"
            )

        fill_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM paper_fills
            WHERE order_id = ?
            """,
            (order_id,),
        ).fetchone()[0]

        if fill_count != 0:
            raise ExpiryBlocked(
                "Pending order unexpectedly has a fill: "
                f"{order_id}"
            )

        rejection_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM order_rejections
            WHERE order_id = ?
            """,
            (order_id,),
        ).fetchone()[0]

        if rejection_count != 0:
            raise ExpiryBlocked(
                "Pending order already has a rejection: "
                f"{order_id}"
            )

        attempt_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM execution_attempts
            WHERE order_id = ?
            """,
            (order_id,),
        ).fetchone()[0]

        if attempt_count != 0:
            raise ExpiryBlocked(
                "Pending order has execution history "
                "that requires manual review: "
                f"{order_id}"
            )

        verified.append(
            (
                order_id,
                ticker,
                side,
                quantity,
            )
        )

    return verified


def build_rejection_reason(
    execution_session: date,
) -> str:
    return (
        "Administrative expiry: the Model 2 order "
        f"for execution session {execution_session.isoformat()} "
        "remained PENDING after that trading session ended. "
        "No paper fill was recorded for this order. "
        "This is an administrative expiry, not a "
        "risk-based rejection."
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Preview or administratively expire stale "
            "Model 2 PENDING orders for a past session."
        )
    )

    parser.add_argument(
        "--session",
        required=True,
        type=date.fromisoformat,
        help="Expired execution session: YYYY-MM-DD.",
    )

    parser.add_argument(
        "--apply",
        action="store_true",
        help=(
            "Explicitly authorize the expiry transaction."
        ),
    )

    parser.add_argument(
        "--confirm",
        default="",
        help=(
            "When --apply is used, must equal "
            "EXPIRE-MODEL2-ORDERS."
        ),
    )

    args = parser.parse_args()

    if (
        args.apply
        and args.confirm != CONFIRMATION_TEXT
    ):
        print(
            "BLOCKED: explicit expiry confirmation "
            "was not provided.",
            file=sys.stderr,
        )
        return 1

    paths = get_model2_paths()

    model1_db = Path(
        paths.model1_database
    ).expanduser().resolve()

    model2_db = Path(
        paths.model2_database
    ).expanduser().resolve()

    observation_db = Path(
        paths.observation_database
    ).expanduser().resolve()

    if model2_db in {
        model1_db,
        observation_db,
    }:
        print(
            "BLOCKED: Model 2 database is not isolated.",
            file=sys.stderr,
        )
        return 1

    if not model2_db.is_file():
        print(
            "BLOCKED: Model 2 database does not exist.",
            file=sys.stderr,
        )
        return 1

    now_et = datetime.now(
        timezone.utc
    ).astimezone(NEW_YORK)

    mode = (
        "APPLY"
        if args.apply
        else "PREVIEW"
    )

    print(
        f"Model 2 administrative expiry — {mode}"
    )
    print(
        "======================================"
    )
    print(f"Database: {model2_db}")
    print(f"Current time: {now_et.isoformat()}")
    print(
        f"Execution session: {args.session}"
    )
    print(
        f"Reason code: {REJECTION_CODE}"
    )
    print()

    database_mode = (
        "rw"
        if args.apply
        else "ro"
    )

    uri = (
        model2_db.as_uri()
        + f"?mode={database_mode}"
    )

    try:
        with sqlite3.connect(
            uri,
            uri=True,
            timeout=15,
            isolation_level=None,
        ) as connection:

            connection.execute(
                "PRAGMA foreign_keys = ON"
            )

            connection.execute(
                "PRAGMA busy_timeout = 15000"
            )

            if not args.apply:
                connection.execute(
                    "PRAGMA query_only = ON"
                )

            transaction_started = False

            try:
                if args.apply:
                    connection.execute(
                        "BEGIN IMMEDIATE"
                    )
                    transaction_started = True

                verified = verify_database(
                    connection,
                    execution_session=args.session,
                    now_et=now_et,
                )

                print(
                    f"Verified stale orders: "
                    f"{len(verified)}"
                )

                for (
                    order_id,
                    ticker,
                    side,
                    quantity,
                ) in verified:
                    print(
                        f"  {ticker}: "
                        f"{side} {quantity} "
                        f"| {order_id}"
                    )

                print()

                if not args.apply:
                    print(
                        "PREVIEW PASSED. "
                        "No database changes were made."
                    )
                    print()
                    print(
                        "To authorize expiry, run:"
                    )
                    print(
                        ".\\.venv\\Scripts\\python.exe "
                        ".\\model2_expire_orders.py "
                        f"--session {args.session.isoformat()} "
                        "--apply "
                        "--confirm EXPIRE-MODEL2-ORDERS"
                    )

                    return 0

                recorded_at = datetime.now(
                    timezone.utc
                ).isoformat()

                reason = build_rejection_reason(
                    args.session
                )

                for (
                    order_id,
                    ticker,
                    side,
                    quantity,
                ) in verified:

                    connection.execute(
                        """
                        INSERT INTO order_rejections (
                            order_id,
                            rejection_code,
                            rejection_reason,
                            rejected_at_utc
                        )
                        VALUES (?, ?, ?, ?)
                        """,
                        (
                            order_id,
                            REJECTION_CODE,
                            reason,
                            recorded_at,
                        ),
                    )

                    changed = connection.execute(
                        """
                        UPDATE paper_orders
                        SET status = 'REJECTED'
                        WHERE order_id = ?
                          AND status = 'PENDING'
                          AND execution_session = ?
                          AND model_version = ?
                        """,
                        (
                            order_id,
                            args.session.isoformat(),
                            MODEL_2_VERSION,
                        ),
                    )

                    if changed.rowcount != 1:
                        raise ExpiryBlocked(
                            "Could not transition exactly "
                            "one order: "
                            f"{order_id}"
                        )

                expected_count = len(verified)

                final_pending = connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM paper_orders
                    WHERE execution_session = ?
                      AND model_version = ?
                      AND status = 'PENDING'
                    """,
                    (
                        args.session.isoformat(),
                        MODEL_2_VERSION,
                    ),
                ).fetchone()[0]

                if final_pending != 0:
                    raise ExpiryBlocked(
                        "Pending stale orders remain "
                        "after expiry transaction."
                    )

                new_rejections = connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM order_rejections
                    WHERE rejection_code = ?
                      AND rejected_at_utc = ?
                      AND order_id IN (
                          SELECT order_id
                          FROM paper_orders
                          WHERE execution_session = ?
                            AND model_version = ?
                      )
                    """,
                    (
                        REJECTION_CODE,
                        recorded_at,
                        args.session.isoformat(),
                        MODEL_2_VERSION,
                    ),
                ).fetchone()[0]

                if new_rejections != expected_count:
                    raise ExpiryBlocked(
                        "Final rejection-count verification "
                        "failed."
                    )

                connection.execute(
                    "COMMIT"
                )
                transaction_started = False

                print(
                    "APPLY COMPLETE."
                )
                print(
                    f"Orders administratively expired: "
                    f"{expected_count}"
                )
                print(
                    "Order status: REJECTED"
                )
                print(
                    f"Rejection code: "
                    f"{REJECTION_CODE}"
                )
                print(
                    "No fills or execution attempts "
                    "were created by this script."
                )

                return 0

            except BaseException:
                if (
                    transaction_started
                    and connection.in_transaction
                ):
                    connection.execute(
                        "ROLLBACK"
                    )

                raise

    except (
        ExpiryBlocked,
        sqlite3.Error,
    ) as exc:
        print(
            f"BLOCKED: {exc}",
            file=sys.stderr,
        )

        print(
            "No expiry transaction was committed.",
            file=sys.stderr,
        )

        return 1


if __name__ == "__main__":
    raise SystemExit(main())