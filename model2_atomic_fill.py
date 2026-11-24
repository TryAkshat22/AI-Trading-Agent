
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable
from uuid import uuid4

from model2_config import (
    MODEL_2_ACCOUNT_ID,
    MODEL_2_VERSION,
)
from model2_execution_readiness import check_execution_window
from trading.orders import Fill, OrderStatus


class Model2AtomicFillError(RuntimeError):
    """The proposed paper fill cannot be committed safely."""


@dataclass(frozen=True)
class Model2AtomicFillResult:
    order_id: str
    fill_id: str
    attempt_id: str
    execution_run_id: str


def _utc(value: datetime) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise Model2AtomicFillError(
            "Clock must return a timezone-aware datetime."
        )

    return value.astimezone(timezone.utc)


def _parse_utc(value: str) -> datetime:
    try:
        return _utc(
            datetime.fromisoformat(
                value.replace("Z", "+00:00")
            )
        )
    except (TypeError, ValueError) as exc:
        raise Model2AtomicFillError(
            "Stored observation timestamp is invalid."
        ) from exc


def commit_model2_test_fill(
    *,
    database_path: str | Path,
    fill: Fill,
    execution_run_id: str,
    clock: Callable[[], datetime],
    after_fill_insert: Callable[[], None] | None = None,
) -> Model2AtomicFillResult:
    """
    TEST-HARNESS PERSISTENCE PRIMITIVE.

    This function deliberately DOES NOT assess risk,
    rebuild a portfolio, fetch prices, or decide
    whether an order should trade.

    It must not be called on either live trading DB.
    A later executor must perform those operations
    under the same write lock before using this
    persistence sequence.
    """
    path = Path(database_path).expanduser().resolve()

    if not path.is_file():
        raise Model2AtomicFillError(
            "Test trading database does not exist."
        )

    # Prevent accidental invocation against either
    # default persistent paper-trading database.
    from model2_config import get_model2_paths

    paths = get_model2_paths()

    protected = {
        Path(paths.model1_database).resolve(),
        Path(paths.model2_database).resolve(),
        Path(paths.observation_database).resolve(),
    }

    if path in protected:
        raise Model2AtomicFillError(
            "This test-only component cannot write "
            "to a configured trading or observation database."
        )

    if not execution_run_id.strip():
        raise Model2AtomicFillError(
            "Execution run ID cannot be blank."
        )

    session = fill.execution_session

    if (
        not isinstance(session, date)
        or isinstance(session, datetime)
    ):
        raise Model2AtomicFillError(
            "Fill execution session must be a date."
        )

    fill_id = str(uuid4())
    attempt_id = str(uuid4())

    uri = path.as_uri() + "?mode=rw"

    try:
        with sqlite3.connect(
            uri,
            uri=True,
            timeout=15,
            isolation_level=None,
        ) as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA busy_timeout = 15000")
            connection.execute("BEGIN IMMEDIATE")

            try:
                now = _utc(clock())
                check_execution_window(session, now)

                accounts = connection.execute(
                    "SELECT account_id FROM paper_accounts"
                ).fetchall()

                if accounts != [(MODEL_2_ACCOUNT_ID,)]:
                    raise Model2AtomicFillError(
                        "Unexpected account in test database."
                    )

                order = connection.execute(
                    """
                    SELECT
                        ticker,
                        side,
                        quantity,
                        execution_session,
                        status,
                        model_version
                    FROM paper_orders
                    WHERE order_id = ?
                    """,
                    (fill.order_id,),
                ).fetchone()

                if order is None:
                    raise Model2AtomicFillError(
                        "Order does not exist."
                    )

                if order[4] != OrderStatus.PENDING.value:
                    raise Model2AtomicFillError(
                        "Order is not PENDING."
                    )

                if order[5] != MODEL_2_VERSION:
                    raise Model2AtomicFillError(
                        "Order belongs to another model."
                    )

                if (
                    order[0] != fill.ticker
                    or order[1] != fill.side.value
                    or order[2] != fill.quantity
                    or order[3] != session.isoformat()
                    or fill.status != OrderStatus.FILLED
                ):
                    raise Model2AtomicFillError(
                        "Fill does not match the stored order."
                    )

                prior_fill = connection.execute(
                    """
                    SELECT 1 FROM paper_fills
                    WHERE order_id = ?
                    """,
                    (fill.order_id,),
                ).fetchone()

                prior_attempt = connection.execute(
                    """
                    SELECT 1 FROM execution_attempts
                    WHERE order_id = ?
                    """,
                    (fill.order_id,),
                ).fetchone()

                if prior_fill or prior_attempt:
                    raise Model2AtomicFillError(
                        "Order already has a fill or "
                        "an execution attempt requiring review."
                    )

                provenance = connection.execute(
                    """
                    SELECT
                        l.ticker,
                        l.execution_session,
                        l.bar_start_utc,
                        l.bar_end_utc,
                        l.retrieved_at_utc,
                        l.reference_price,
                        l.price_field,
                        i.safe_to_use
                    FROM model2_execution_observation_lineage AS l
                    JOIN ingestion_runs AS i
                      ON i.run_id = l.execution_run_id
                    WHERE l.execution_run_id = ?
                    """,
                    (execution_run_id,),
                ).fetchone()

                if provenance is None:
                    raise Model2AtomicFillError(
                        "Execution provenance does not exist."
                    )

                (
                    observed_ticker,
                    observed_session,
                    bar_start_text,
                    bar_end_text,
                    retrieved_text,
                    observed_price,
                    price_field,
                    safe_to_use,
                ) = provenance

                bar_start = _parse_utc(bar_start_text)
                bar_end = _parse_utc(bar_end_text)
                retrieved = _parse_utc(retrieved_text)

                if (
                    observed_ticker != fill.ticker
                    or observed_session != session.isoformat()
                    or price_field != "Close"
                    or safe_to_use != 1
                    or bar_end - bar_start != timedelta(minutes=1)
                    or bar_end > retrieved
                    or retrieved > now
                    or now - bar_end > timedelta(minutes=5)
                ):
                    raise Model2AtomicFillError(
                        "Execution observation is invalid or stale."
                    )

                # Compare at the portfolio's money precision.
                from trading.portfolio import money

                if money(observed_price) != money(
                    fill.reference_price
                ):
                    raise Model2AtomicFillError(
                        "Fill reference price differs "
                        "from recorded execution provenance."
                    )

                recorded_at = now.isoformat()

                connection.execute(
                    """
                    INSERT INTO execution_attempts (
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
                    VALUES (?, ?, ?, ?, 'STARTED', ?, NULL, NULL, NULL)
                    """,
                    (
                        attempt_id,
                        fill.order_id,
                        execution_run_id,
                        retrieved_text,
                        recorded_at,
                    ),
                )

                connection.execute(
                    """
                    INSERT INTO paper_fills (
                        fill_id,
                        order_id,
                        ticker,
                        side,
                        quantity,
                        execution_session,
                        reference_price,
                        fill_price,
                        gross_value,
                        fees,
                        slippage_cost,
                        realized_pnl,
                        source_run_id,
                        created_at_utc
                    )
                    VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        NULL, ?
                    )
                    """,
                    (
                        fill_id,
                        fill.order_id,
                        fill.ticker,
                        fill.side.value,
                        fill.quantity,
                        session.isoformat(),
                        str(fill.reference_price),
                        str(fill.fill_price),
                        str(fill.gross_value),
                        str(fill.fees),
                        str(fill.slippage_cost),
                        str(fill.realized_pnl),
                        recorded_at,
                    ),
                )

                if after_fill_insert is not None:
                    after_fill_insert()

                connection.execute(
                    """
                    INSERT INTO fill_execution_lineage (
                        fill_id, execution_run_id
                    )
                    VALUES (?, ?)
                    """,
                    (fill_id, execution_run_id),
                )

                changed = connection.execute(
                    """
                    UPDATE paper_orders
                    SET status = 'FILLED'
                    WHERE order_id = ?
                      AND status = 'PENDING'
                    """,
                    (fill.order_id,),
                )

                if changed.rowcount != 1:
                    raise Model2AtomicFillError(
                        "Order status changed during execution."
                    )

                # Check the actual time AGAIN before commit.
                completed_at = _utc(clock())
                check_execution_window(session, completed_at)

                if completed_at - bar_end > timedelta(minutes=5):
                    raise Model2AtomicFillError(
                        "Observation became stale before commit."
                    )

                connection.execute(
                    """
                    UPDATE execution_attempts
                    SET outcome = 'FILLED',
                        completed_at_utc = ?
                    WHERE attempt_id = ?
                      AND outcome = 'STARTED'
                    """,
                    (
                        completed_at.isoformat(),
                        attempt_id,
                    ),
                )

                connection.execute("COMMIT")

            except BaseException:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise

    except sqlite3.Error as exc:
        raise Model2AtomicFillError(
            f"Atomic fill transaction failed: {exc}"
        ) from exc

    return Model2AtomicFillResult(
        order_id=fill.order_id,
        fill_id=fill_id,
        attempt_id=attempt_id,
        execution_run_id=execution_run_id,
    )