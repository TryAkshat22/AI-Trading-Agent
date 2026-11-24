from __future__ import annotations

import sqlite3

from datetime import date, datetime, timezone
from pathlib import Path

from model2_config import (
    MODEL_2_ACCOUNT_ID,
    MODEL_2_VERSION,
    get_model2_paths,
)

from model2_execution_readiness import (
    check_execution_window,
)


class Model2PreflightError(RuntimeError):
    """
    Model 2 execution preflight failed.

    Preflight is read-only. It never creates, modifies,
    fills, rejects, or deletes an order.
    """


def _utc(
    value: datetime,
) -> datetime:
    """
    Require a timezone-aware datetime and normalize it
    to UTC.
    """

    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise Model2PreflightError(
            "Preflight clock must be timezone-aware."
        )

    return value.astimezone(
        timezone.utc
    )


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


def _load_execution_attempts(
    connection: sqlite3.Connection,
    order_id: str,
) -> tuple[tuple[str, str | None], ...]:
    """
    Return attempt_id/outcome pairs for an order.

    Do not assume optional timestamp columns exist.
    """

    if not _table_exists(
        connection,
        "execution_attempts",
    ):
        raise Model2PreflightError(
            "execution_attempts table is missing."
        )

    rows = connection.execute(
        """
        SELECT
            attempt_id,
            outcome
        FROM execution_attempts
        WHERE order_id = ?
        ORDER BY attempt_id
        """,
        (order_id,),
    ).fetchall()

    return tuple(
        (
            str(row[0]),
            (
                str(row[1]).strip().upper()
                if row[1] is not None
                else None
            ),
        )
        for row in rows
    )


def _verify_pending_order(
    connection: sqlite3.Connection,
    *,
    order_id: str,
) -> None:
    """
    Validate an order that is still eligible to execute.
    """

    fill_count = _count_fills(
        connection,
        order_id,
    )

    if fill_count != 0:
        raise Model2PreflightError(
            f"PENDING order {order_id} "
            "already has a fill."
        )

    rejection_count = _count_rejections(
        connection,
        order_id,
    )

    if rejection_count != 0:
        raise Model2PreflightError(
            f"PENDING order {order_id} "
            "already has a rejection record."
        )

    attempts = _load_execution_attempts(
        connection,
        order_id,
    )

    for attempt_id, outcome in attempts:

        if outcome in {
            "FILLED",
            "REJECTED",
        }:
            raise Model2PreflightError(
                f"PENDING order {order_id} has "
                f"terminal execution attempt "
                f"{attempt_id} with outcome "
                f"{outcome}."
            )

        if outcome in {
            "STARTED",
            None,
            "",
        }:
            raise Model2PreflightError(
                f"PENDING order {order_id} has "
                f"unfinished execution attempt "
                f"{attempt_id}."
            )

        # Operational failures from an earlier attempt
        # remain visible but do not make a still-PENDING
        # order terminal. A later guarded run may retry
        # after all current checks pass.
        if outcome == "FAILED":
            continue

        raise Model2PreflightError(
            f"Order {order_id} has execution attempt "
            f"{attempt_id} with unexpected outcome "
            f"{outcome}."
        )


def _verify_filled_order(
    connection: sqlite3.Connection,
    *,
    order_id: str,
) -> None:
    """
    Validate a terminal FILLED order.

    A correctly filled order is safe to skip while
    preflighting the remaining PENDING orders.
    """

    fill_count = _count_fills(
        connection,
        order_id,
    )

    if fill_count != 1:
        raise Model2PreflightError(
            f"FILLED order {order_id} must have "
            "exactly one fill; "
            f"found {fill_count}."
        )

    rejection_count = _count_rejections(
        connection,
        order_id,
    )

    if rejection_count != 0:
        raise Model2PreflightError(
            f"FILLED order {order_id} also has "
            "a rejection record."
        )

    attempts = _load_execution_attempts(
        connection,
        order_id,
    )

    filled_attempts = [
        attempt_id
        for attempt_id, outcome in attempts
        if outcome == "FILLED"
    ]

    if len(filled_attempts) != 1:
        raise Model2PreflightError(
            f"FILLED order {order_id} must have "
            "exactly one FILLED execution attempt; "
            f"found {len(filled_attempts)}."
        )

    unfinished_attempts = [
        attempt_id
        for attempt_id, outcome in attempts
        if outcome in {
            "STARTED",
            None,
            "",
        }
    ]

    if unfinished_attempts:
        raise Model2PreflightError(
            f"FILLED order {order_id} has "
            "an unfinished execution attempt."
        )


def _verify_rejected_order(
    connection: sqlite3.Connection,
    *,
    order_id: str,
) -> None:
    """
    Validate a terminal REJECTED order.

    Administrative expiries and risk rejections are
    terminal and should not block another PENDING order
    from the same execution session.
    """

    fill_count = _count_fills(
        connection,
        order_id,
    )

    if fill_count != 0:
        raise Model2PreflightError(
            f"REJECTED order {order_id} "
            "also has a fill."
        )

    rejection_count = _count_rejections(
        connection,
        order_id,
    )

    if rejection_count < 1:
        raise Model2PreflightError(
            f"REJECTED order {order_id} has "
            "no rejection record."
        )

    attempts = _load_execution_attempts(
        connection,
        order_id,
    )

    unfinished_attempts = [
        attempt_id
        for attempt_id, outcome in attempts
        if outcome in {
            "STARTED",
            None,
            "",
        }
    ]

    if unfinished_attempts:
        raise Model2PreflightError(
            f"REJECTED order {order_id} has "
            "an unfinished execution attempt."
        )


def inspect_execution_prerequisites(
    *,
    execution_session: date,
    now: datetime,
) -> tuple[str, ...]:
    """
    Read-only Model 2 execution preflight.

    Returns ONLY orders that are still PENDING for the
    requested execution session.

    Terminal orders are verified and skipped:

        FILLED
            already executed successfully

        REJECTED
            already terminal, including administrative
            expiry or execution-time risk rejection

    An unexpected or internally inconsistent state still
    blocks execution.

    No database changes are made.
    """

    if not isinstance(
        execution_session,
        date,
    ):
        raise TypeError(
            "execution_session must be "
            "a datetime.date."
        )

    now = _utc(now)

    # --------------------------------------------------------
    # EXECUTION-TIME GATE
    # --------------------------------------------------------

    check_execution_window(
        execution_session,
        now,
    )

    # --------------------------------------------------------
    # DATABASE ISOLATION
    # --------------------------------------------------------

    paths = get_model2_paths()

    model2_database = Path(
        paths.model2_database
    ).expanduser().resolve()

    model1_database = Path(
        paths.model1_database
    ).expanduser().resolve()

    observation_database = Path(
        paths.observation_database
    ).expanduser().resolve()

    if (
        model2_database
        == model1_database
    ):
        raise Model2PreflightError(
            "Model 2 database resolves to "
            "Model 1."
        )

    if (
        model2_database
        == observation_database
    ):
        raise Model2PreflightError(
            "Model 2 trading database must be "
            "separate from its observation database."
        )

    if not model2_database.is_file():
        raise Model2PreflightError(
            "Model 2 trading database is missing."
        )

    # --------------------------------------------------------
    # READ-ONLY DATABASE CHECKS
    # --------------------------------------------------------

    uri = (
        model2_database.as_uri()
        + "?mode=ro"
    )

    try:

        with sqlite3.connect(
            uri,
            uri=True,
            timeout=10,
        ) as connection:

            connection.execute(
                "PRAGMA query_only = ON"
            )

            connection.execute(
                "PRAGMA foreign_keys = ON"
            )

            connection.execute(
                "PRAGMA busy_timeout = 10000"
            )

            required_tables = (
                "paper_accounts",
                "paper_orders",
                "paper_fills",
                "order_rejections",
                "execution_attempts",
            )

            missing_tables = [
                table_name
                for table_name in required_tables
                if not _table_exists(
                    connection,
                    table_name,
                )
            ]

            if missing_tables:
                raise Model2PreflightError(
                    "Required Model 2 table(s) "
                    "missing: "
                    + ", ".join(
                        missing_tables
                    )
                )

            # ------------------------------------------------
            # ACCOUNT CHECK
            # ------------------------------------------------

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
                raise Model2PreflightError(
                    "Unexpected Model 2 account "
                    "configuration."
                )

            # ------------------------------------------------
            # SESSION ORDERS
            # ------------------------------------------------

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
                (
                    execution_session
                    .isoformat(),
                ),
            ).fetchall()

            if not rows:
                raise Model2PreflightError(
                    "No orders are scheduled for "
                    "the requested execution session."
                )

            pending_order_ids: list[
                str
            ] = []

            seen_order_ids: set[str] = (
                set()
            )

            seen_tickers: set[str] = (
                set()
            )

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

                model_version = str(
                    model_version
                ).strip()

                # --------------------------------------------
                # BASIC ORDER IDENTITY
                # --------------------------------------------

                if not order_id:
                    raise Model2PreflightError(
                        "Order has a blank order ID."
                    )

                if (
                    order_id
                    in seen_order_ids
                ):
                    raise Model2PreflightError(
                        "Duplicate order returned by "
                        f"preflight: {order_id}"
                    )

                seen_order_ids.add(
                    order_id
                )

                if not ticker:
                    raise Model2PreflightError(
                        f"Order {order_id} has "
                        "a blank ticker."
                    )

                if ticker in seen_tickers:
                    raise Model2PreflightError(
                        "More than one order exists "
                        f"for ticker {ticker} in "
                        "the same execution session."
                    )

                seen_tickers.add(
                    ticker
                )

                if side not in {
                    "BUY",
                    "SELL",
                }:
                    raise Model2PreflightError(
                        f"Order {order_id} has "
                        f"invalid side {side}."
                    )

                try:
                    quantity_int = int(
                        quantity
                    )
                except (
                    TypeError,
                    ValueError,
                ) as exc:
                    raise Model2PreflightError(
                        f"Order {order_id} has "
                        "invalid quantity."
                    ) from exc

                if quantity_int <= 0:
                    raise Model2PreflightError(
                        f"Order {order_id} has "
                        "nonpositive quantity."
                    )

                if (
                    stored_session
                    != execution_session
                    .isoformat()
                ):
                    raise Model2PreflightError(
                        f"Order {order_id} has "
                        "the wrong execution session."
                    )

                if (
                    model_version
                    != MODEL_2_VERSION
                ):
                    raise Model2PreflightError(
                        f"Order {order_id} belongs "
                        "to another model version."
                    )

                # ============================================
                # STATUS HANDLING
                # ============================================

                if status == "PENDING":

                    _verify_pending_order(
                        connection,
                        order_id=order_id,
                    )

                    pending_order_ids.append(
                        order_id
                    )

                    continue

                # --------------------------------------------
                # IMPORTANT FIX
                #
                # A terminal order is verified and skipped.
                #
                # It no longer blocks other PENDING orders
                # in the same execution session.
                # --------------------------------------------

                if status == "FILLED":

                    _verify_filled_order(
                        connection,
                        order_id=order_id,
                    )

                    continue

                if status == "REJECTED":

                    _verify_rejected_order(
                        connection,
                        order_id=order_id,
                    )

                    continue

                raise Model2PreflightError(
                    f"Order {order_id} has "
                    f"unexpected status {status}."
                )

            # ------------------------------------------------
            # Nothing remains eligible.
            # ------------------------------------------------

            if not pending_order_ids:
                 raise Model2PreflightError(
        "No PENDING orders remain for the requested "
        "execution session. All scheduled orders are "
        "terminal and therefore not PENDING."
    )

            return tuple(
                pending_order_ids
            )

    except Model2PreflightError:
        raise

    except sqlite3.Error as exc:
        raise Model2PreflightError(
            "Could not complete Model 2 "
            f"execution preflight: {exc}"
        ) from exc