from __future__ import annotations

import argparse
import sqlite3
import sys

from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas_market_calendars as mcal

from model2_config import (
    MODEL_2_ACCOUNT_ID,
    MODEL_2_VERSION,
    get_model2_paths,
)


NEW_YORK = ZoneInfo("America/New_York")

REJECTION_CODE = "EXECUTION_WINDOW_EXPIRED"

CONFIRMATION_TEXT = "EXPIRE-STALE-MODEL2"


class StaleOrderExpiryError(RuntimeError):
    """A guarded stale-order expiry check failed."""


def _table_exists(
    connection: sqlite3.Connection,
    table_name: str,
) -> bool:

    row = connection.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table'
          AND name = ?
        """,
        (table_name,),
    ).fetchone()

    return row is not None


def _validate_session(
    execution_session: date,
    now_et: datetime,
) -> None:

    if execution_session >= now_et.date():
        raise StaleOrderExpiryError(
            "Only a completed past execution session "
            "may be expired. Today's or future orders "
            "are blocked."
        )

    calendar = mcal.get_calendar(
        "NYSE"
    )

    schedule = calendar.schedule(
        start_date=execution_session,
        end_date=execution_session,
    )

    if schedule.empty:
        raise StaleOrderExpiryError(
            f"{execution_session} was not a valid "
            "NYSE trading session."
        )


def _load_session_orders(
    connection: sqlite3.Connection,
    execution_session: date,
):
    return connection.execute(
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
        (
            execution_session.isoformat(),
        ),
    ).fetchall()


def _count_fills(
    connection: sqlite3.Connection,
    order_id: str,
) -> int:

    return int(
        connection.execute(
            """
            SELECT COUNT(*)
            FROM paper_fills
            WHERE order_id = ?
            """,
            (order_id,),
        ).fetchone()[0]
    )


def _count_rejections(
    connection: sqlite3.Connection,
    order_id: str,
) -> int:

    return int(
        connection.execute(
            """
            SELECT COUNT(*)
            FROM order_rejections
            WHERE order_id = ?
            """,
            (order_id,),
        ).fetchone()[0]
    )


def _count_attempts(
    connection: sqlite3.Connection,
    order_id: str,
) -> int:

    return int(
        connection.execute(
            """
            SELECT COUNT(*)
            FROM execution_attempts
            WHERE order_id = ?
            """,
            (order_id,),
        ).fetchone()[0]
    )


def verify_expiry(
    connection: sqlite3.Connection,
    *,
    execution_session: date,
    now_et: datetime,
) -> tuple[
    tuple[str, str, str, int],
    ...,
]:
    """
    Verify stale PENDING orders in one completed session.

    Returns:
        (order_id, ticker, side, quantity)

    FILLED and REJECTED orders are verified but skipped.

    No writes occur here.
    """

    _validate_session(
        execution_session,
        now_et,
    )

    required_tables = (
        "paper_accounts",
        "paper_orders",
        "paper_fills",
        "order_rejections",
        "execution_attempts",
    )

    missing = [
        table_name
        for table_name in required_tables
        if not _table_exists(
            connection,
            table_name,
        )
    ]

    if missing:
        raise StaleOrderExpiryError(
            "Required table(s) missing: "
            + ", ".join(missing)
        )

    accounts = connection.execute(
        """
        SELECT account_id
        FROM paper_accounts
        ORDER BY account_id
        """
    ).fetchall()

    if accounts != [
        (MODEL_2_ACCOUNT_ID,)
    ]:
        raise StaleOrderExpiryError(
            "Unexpected Model 2 account configuration."
        )

    rows = _load_session_orders(
        connection,
        execution_session,
    )

    if not rows:
        raise StaleOrderExpiryError(
            "No Model 2 orders exist for "
            f"execution session {execution_session}."
        )

    verified_pending = []

    seen_order_ids = set()
    seen_tickers = set()

    for (
        order_id,
        ticker,
        side,
        quantity,
        stored_session,
        status,
        model_version,
    ) in rows:

        order_id = str(
            order_id
        ).strip()

        ticker = str(
            ticker
        ).strip().upper()

        side = str(
            side
        ).strip().upper()

        status = str(
            status
        ).strip().upper()

        if not order_id:
            raise StaleOrderExpiryError(
                "Blank order ID found."
            )

        if order_id in seen_order_ids:
            raise StaleOrderExpiryError(
                f"Duplicate order ID: {order_id}"
            )

        seen_order_ids.add(
            order_id
        )

        if not ticker:
            raise StaleOrderExpiryError(
                f"Blank ticker on {order_id}."
            )

        if ticker in seen_tickers:
            raise StaleOrderExpiryError(
                "Duplicate ticker in execution "
                f"session: {ticker}"
            )

        seen_tickers.add(
            ticker
        )

        if side not in {
            "BUY",
            "SELL",
        }:
            raise StaleOrderExpiryError(
                f"Unexpected side on {order_id}: "
                f"{side}"
            )

        try:
            quantity = int(
                quantity
            )
        except (
            TypeError,
            ValueError,
        ) as exc:
            raise StaleOrderExpiryError(
                f"Invalid quantity on {order_id}."
            ) from exc

        if quantity <= 0:
            raise StaleOrderExpiryError(
                f"Nonpositive quantity on {order_id}."
            )

        if (
            stored_session
            != execution_session.isoformat()
        ):
            raise StaleOrderExpiryError(
                f"Wrong execution session on "
                f"{order_id}."
            )

        if (
            model_version
            != MODEL_2_VERSION
        ):
            raise StaleOrderExpiryError(
                f"Unexpected model version on "
                f"{order_id}."
            )

        fill_count = _count_fills(
            connection,
            order_id,
        )

        rejection_count = (
            _count_rejections(
                connection,
                order_id,
            )
        )

        attempt_count = (
            _count_attempts(
                connection,
                order_id,
            )
        )

        # -------------------------------------------------
        # Still pending
        # -------------------------------------------------

        if status == "PENDING":

            if fill_count != 0:
                raise StaleOrderExpiryError(
                    f"PENDING order {order_id} "
                    "already has a fill."
                )

            if rejection_count != 0:
                raise StaleOrderExpiryError(
                    f"PENDING order {order_id} "
                    "already has a rejection."
                )

            # A stale PENDING order with any execution
            # attempt needs separate manual review.
            if attempt_count != 0:
                raise StaleOrderExpiryError(
                    f"PENDING order {order_id} has "
                    f"{attempt_count} execution "
                    "attempt(s). Manual review required."
                )

            verified_pending.append(
                (
                    order_id,
                    ticker,
                    side,
                    quantity,
                )
            )

            continue

        # -------------------------------------------------
        # Already filled
        # -------------------------------------------------

        if status == "FILLED":

            if fill_count != 1:
                raise StaleOrderExpiryError(
                    f"FILLED order {order_id} must "
                    "have exactly one fill."
                )

            if rejection_count != 0:
                raise StaleOrderExpiryError(
                    f"FILLED order {order_id} also "
                    "has a rejection."
                )

            continue

        # -------------------------------------------------
        # Already rejected
        # -------------------------------------------------

        if status == "REJECTED":

            if fill_count != 0:
                raise StaleOrderExpiryError(
                    f"REJECTED order {order_id} "
                    "also has a fill."
                )

            if rejection_count < 1:
                raise StaleOrderExpiryError(
                    f"REJECTED order {order_id} "
                    "has no rejection record."
                )

            continue

        raise StaleOrderExpiryError(
            f"Unexpected order status on "
            f"{order_id}: {status}"
        )

    return tuple(
        verified_pending
    )


def expire_orders(
    connection: sqlite3.Connection,
    *,
    execution_session: date,
    orders: tuple[
        tuple[str, str, str, int],
        ...,
    ],
) -> None:

    if not orders:
        return

    recorded_at = datetime.now(
        timezone.utc
    ).isoformat()

    reason = (
        "Administrative expiry: the Model 2 order "
        f"for execution session {execution_session} "
        "remained PENDING after that trading session "
        "ended. No paper fill was recorded for this "
        "order. This is an administrative expiry, "
        "not a risk-based rejection."
    )

    for (
        order_id,
        ticker,
        side,
        quantity,
    ) in orders:

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
              AND execution_session = ?
              AND model_version = ?
              AND status = 'PENDING'
            """,
            (
                order_id,
                execution_session.isoformat(),
                MODEL_2_VERSION,
            ),
        )

        if changed.rowcount != 1:
            raise StaleOrderExpiryError(
                "Could not transition exactly "
                f"one PENDING order: {order_id}"
            )


def verify_after_expiry(
    connection: sqlite3.Connection,
    *,
    execution_session: date,
    expired_order_ids: tuple[str, ...],
) -> None:

    for order_id in expired_order_ids:

        row = connection.execute(
            """
            SELECT status
            FROM paper_orders
            WHERE order_id = ?
              AND execution_session = ?
              AND model_version = ?
            """,
            (
                order_id,
                execution_session.isoformat(),
                MODEL_2_VERSION,
            ),
        ).fetchone()

        if row != (
            "REJECTED",
        ):
            raise StaleOrderExpiryError(
                "Post-expiry order verification "
                f"failed: {order_id}"
            )

        rejection_count = int(
            connection.execute(
                """
                SELECT COUNT(*)
                FROM order_rejections
                WHERE order_id = ?
                  AND rejection_code = ?
                """,
                (
                    order_id,
                    REJECTION_CODE,
                ),
            ).fetchone()[0]
        )

        if rejection_count != 1:
            raise StaleOrderExpiryError(
                "Post-expiry rejection verification "
                f"failed: {order_id}"
            )

        fill_count = _count_fills(
            connection,
            order_id,
        )

        if fill_count != 0:
            raise StaleOrderExpiryError(
                "Expired order unexpectedly "
                f"has a fill: {order_id}"
            )


def main() -> int:

    parser = argparse.ArgumentParser(
        description=(
            "Preview or administratively expire "
            "stale Model 2 PENDING orders from one "
            "completed execution session."
        )
    )

    parser.add_argument(
        "--session",
        required=True,
        type=date.fromisoformat,
        help=(
            "Past execution session YYYY-MM-DD."
        ),
    )

    parser.add_argument(
        "--apply",
        action="store_true",
        help=(
            "Actually write administrative expiry "
            "records and transition verified "
            "PENDING orders to REJECTED."
        ),
    )

    parser.add_argument(
        "--confirm",
        default="",
        help=(
            "With --apply, must equal "
            "EXPIRE-STALE-MODEL2."
        ),
    )

    args = parser.parse_args()

    if (
        args.apply
        and args.confirm
        != CONFIRMATION_TEXT
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
            "BLOCKED: Model 2 database "
            "is not isolated.",
            file=sys.stderr,
        )
        return 1

    if not model2_db.is_file():
        print(
            "BLOCKED: Model 2 database "
            "does not exist.",
            file=sys.stderr,
        )
        return 1

    now_et = datetime.now(
        timezone.utc
    ).astimezone(
        NEW_YORK
    )

    mode = (
        "APPLY"
        if args.apply
        else "PREVIEW"
    )

    print(
        f"Model 2 stale-order expiry: {mode}"
    )
    print(
        "================================="
    )
    print(
        f"Database: {model2_db}"
    )
    print(
        f"Current NY time: "
        f"{now_et.isoformat()}"
    )
    print(
        f"Execution session: "
        f"{args.session}"
    )
    print(
        f"Reason code: "
        f"{REJECTION_CODE}"
    )
    print()

    db_mode = (
        "rw"
        if args.apply
        else "ro"
    )

    uri = (
        model2_db.as_uri()
        + f"?mode={db_mode}"
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

                orders = verify_expiry(
                    connection,
                    execution_session=(
                        args.session
                    ),
                    now_et=now_et,
                )

                print(
                    "Verified stale PENDING "
                    f"orders: {len(orders)}"
                )

                for (
                    order_id,
                    ticker,
                    side,
                    quantity,
                ) in orders:

                    print(
                        f"  {ticker}: "
                        f"{side} {quantity} "
                        f"| {order_id}"
                    )

                print()

                if not orders:

                    if transaction_started:
                        connection.execute(
                            "ROLLBACK"
                        )

                    print(
                        "Nothing to expire. "
                        "No database changes made."
                    )

                    return 0

                if not args.apply:

                    print(
                        "PREVIEW PASSED."
                    )

                    print(
                        "No database changes "
                        "were made."
                    )

                    return 0

                expire_orders(
                    connection,
                    execution_session=(
                        args.session
                    ),
                    orders=orders,
                )

                expired_ids = tuple(
                    order_id
                    for (
                        order_id,
                        _,
                        _,
                        _,
                    ) in orders
                )

                verify_after_expiry(
                    connection,
                    execution_session=(
                        args.session
                    ),
                    expired_order_ids=(
                        expired_ids
                    ),
                )

                # Reconfirm this is still a past
                # session immediately before commit.
                commit_now = datetime.now(
                    timezone.utc
                ).astimezone(
                    NEW_YORK
                )

                _validate_session(
                    args.session,
                    commit_now,
                )

                connection.execute(
                    "COMMIT"
                )

                transaction_started = False

                print(
                    "EXPIRY COMMITTED."
                )

                print(
                    f"Expired orders: "
                    f"{len(orders)}"
                )

                return 0

            except Exception:

                if transaction_started:
                    connection.execute(
                        "ROLLBACK"
                    )

                raise

    except Exception as exc:

        print(
            "MODEL 2 STALE-ORDER "
            "EXPIRY BLOCKED",
            file=sys.stderr,
        )

        print(
            f"{type(exc).__name__}: "
            f"{exc}",
            file=sys.stderr,
        )

        return 1


if __name__ == "__main__":
    raise SystemExit(
        main()
    )