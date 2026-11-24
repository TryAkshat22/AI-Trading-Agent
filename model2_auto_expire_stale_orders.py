from __future__ import annotations

import sqlite3
import sys

from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from model2_config import (
    MODEL_2_VERSION,
    get_model2_paths,
)
from model2_expire_stale_orders import (
    expire_orders,
    verify_after_expiry,
    verify_expiry,
)


NEW_YORK = ZoneInfo("America/New_York")


class Model2AutoExpiryError(RuntimeError):
    """Automatic stale-order cleanup was blocked."""


def discover_stale_sessions(
    database: Path,
    *,
    today: date,
) -> tuple[date, ...]:
    """
    Find past execution sessions that still contain
    Model 2 PENDING orders.

    Read only.
    """

    try:
        with sqlite3.connect(
            database.as_uri() + "?mode=ro",
            uri=True,
            timeout=15,
        ) as connection:

            connection.execute(
                "PRAGMA query_only = ON"
            )

            rows = connection.execute(
                """
                SELECT DISTINCT execution_session
                FROM paper_orders
                WHERE model_version = ?
                  AND status = 'PENDING'
                  AND execution_session < ?
                ORDER BY execution_session
                """,
                (
                    MODEL_2_VERSION,
                    today.isoformat(),
                ),
            ).fetchall()

    except sqlite3.Error as exc:
        raise Model2AutoExpiryError(
            "Could not inspect stale Model 2 orders: "
            f"{exc}"
        ) from exc

    sessions = []

    for row in rows:

        try:
            session = date.fromisoformat(
                str(row[0])
            )

        except (
            TypeError,
            ValueError,
        ) as exc:
            raise Model2AutoExpiryError(
                "Invalid execution session stored "
                f"in paper_orders: {row[0]!r}"
            ) from exc

        if session >= today:
            raise Model2AutoExpiryError(
                "Automatic expiry discovered a "
                "non-past execution session."
            )

        sessions.append(
            session
        )

    return tuple(
        sessions
    )


def expire_one_session(
    database: Path,
    *,
    execution_session: date,
    now_et: datetime,
) -> int:
    """
    Expire one fully verified stale execution session.

    All verification and writes occur inside one
    database transaction.
    """

    uri = (
        database.as_uri()
        + "?mode=rw"
    )

    connection = None
    transaction_started = False

    try:

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

        connection.execute(
            "BEGIN IMMEDIATE"
        )

        transaction_started = True

        orders = verify_expiry(
            connection,
            execution_session=execution_session,
            now_et=now_et,
        )

        if not orders:

            connection.execute(
                "ROLLBACK"
            )

            transaction_started = False

            print(
                f"{execution_session}: "
                "nothing to expire."
            )

            return 0

        print(
            f"{execution_session}: "
            f"verified {len(orders)} stale "
            "PENDING order(s)."
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

        expire_orders(
            connection,
            execution_session=execution_session,
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
            execution_session=execution_session,
            expired_order_ids=expired_ids,
        )

        # Reconfirm the session is still in the past
        # immediately before commit.
        commit_now_et = datetime.now(
            timezone.utc
        ).astimezone(
            NEW_YORK
        )

        if execution_session >= commit_now_et.date():
            raise Model2AutoExpiryError(
                "Execution session is no longer "
                "eligible for automatic expiry."
            )

        connection.execute(
            "COMMIT"
        )

        transaction_started = False

        print(
            f"{execution_session}: "
            f"expired {len(orders)} order(s)."
        )

        return len(
            orders
        )

    except Exception:

        if (
            connection is not None
            and transaction_started
        ):
            connection.execute(
                "ROLLBACK"
            )

        raise

    finally:

        if connection is not None:
            connection.close()


def main() -> int:

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
            "MODEL 2 AUTO EXPIRY: BLOCKED",
            file=sys.stderr,
        )

        print(
            "Model 2 trading database is "
            "not isolated.",
            file=sys.stderr,
        )

        return 1

    if not model2_db.is_file():
        print(
            "MODEL 2 AUTO EXPIRY: BLOCKED",
            file=sys.stderr,
        )

        print(
            "Model 2 database does not exist.",
            file=sys.stderr,
        )

        return 1

    now_et = datetime.now(
        timezone.utc
    ).astimezone(
        NEW_YORK
    )

    print(
        "MODEL 2 AUTOMATIC STALE-ORDER EXPIRY"
    )
    print(
        "===================================="
    )
    print(
        f"Current NY time: {now_et.isoformat()}"
    )
    print(
        f"Database: {model2_db}"
    )
    print()

    try:

        sessions = discover_stale_sessions(
            model2_db,
            today=now_et.date(),
        )

        if not sessions:

            print(
                "No stale PENDING Model 2 "
                "orders were found."
            )

            print(
                "AUTO EXPIRY: PASS"
            )

            return 0

        print(
            "Stale execution sessions: "
            + ", ".join(
                session.isoformat()
                for session in sessions
            )
        )

        print()

        total_expired = 0

        for session in sessions:

            expired = expire_one_session(
                model2_db,
                execution_session=session,
                now_et=now_et,
            )

            total_expired += expired

        print()

        print(
            "AUTO EXPIRY: PASS"
        )

        print(
            f"Total orders expired: "
            f"{total_expired}"
        )

        return 0

    except Exception as exc:

        print(
            "MODEL 2 AUTO EXPIRY: BLOCKED",
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