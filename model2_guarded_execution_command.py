from __future__ import annotations

import argparse
import sqlite3
import sys
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable

from model2_config import (
    MODEL_2_VERSION,
    get_model2_paths,
)
from model2_execution_preflight import (
    inspect_execution_prerequisites,
)
from model2_execution_provenance import (
    record_model2_execution_observation,
)
from model2_observation_command import (
    collect_required_observations,
    discover_requirements,
)
from model2_production_executor import (
    Model2ProductionExecutionError,
    execute_model2_order,
)


CONFIRMATION_TEXT = "MODEL2-PAPER"

RISK_REJECTION_CODE = "EXECUTION_RISK_REJECTED"
RISK_REJECTION_PREFIX = (
    "Execution-time risk rejected the trade:"
)


class Model2GuardedExecutionError(RuntimeError):
    """Guarded Model 2 paper execution was blocked."""


@dataclass(frozen=True)
class GuardedExecutionResult:
    order_id: str
    ticker: str
    fill_id: str
    execution_run_id: str
    reference_price: str
    fill_price: str


@dataclass(frozen=True)
class GuardedRejectionResult:
    order_id: str
    ticker: str
    rejection_code: str
    rejection_reason: str


@dataclass(frozen=True)
class GuardedBatchExecutionResult:
    results: tuple[
        GuardedExecutionResult,
        ...,
    ]

    rejections: tuple[
        GuardedRejectionResult,
        ...,
    ] = ()

    @property
    def filled_count(self) -> int:
        return len(self.results)

    @property
    def rejected_count(self) -> int:
        return len(self.rejections)


def _load_ticker(
    database: Path,
    order_id: str,
) -> str:
    try:
        with sqlite3.connect(
            database.as_uri() + "?mode=ro",
            uri=True,
            timeout=10,
        ) as connection:
            connection.execute(
                "PRAGMA query_only = ON"
            )

            row = connection.execute(
                """
                SELECT ticker
                FROM paper_orders
                WHERE order_id = ?
                """,
                (order_id,),
            ).fetchone()

    except sqlite3.Error as exc:
        raise Model2GuardedExecutionError(
            f"Could not read order ticker: {exc}"
        ) from exc

    if row is None:
        raise Model2GuardedExecutionError(
            f"Order disappeared: {order_id}"
        )

    ticker = row[0].strip().upper()

    if not ticker:
        raise Model2GuardedExecutionError(
            f"Order has blank ticker: {order_id}"
        )

    return ticker


def _resolve_databases() -> tuple[
    Path,
    Path,
    Path,
]:
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

    if model2_database == model1_database:
        raise Model2GuardedExecutionError(
            "Model 2 database resolves to Model 1."
        )

    if model2_database == observation_database:
        raise Model2GuardedExecutionError(
            "Model 2 trading and observation "
            "databases are not isolated."
        )

    return (
        model2_database,
        model1_database,
        observation_database,
    )


def _prepare_observations(
    *,
    execution_session: date,
    expected_order_ids: tuple[str, ...],
    model2_database: Path,
    clock: Callable[[], datetime],
):
    initial_requirements = discover_requirements(
        model2_database,
        execution_session,
    )

    if (
        initial_requirements.order_ids
        != expected_order_ids
    ):
        raise Model2GuardedExecutionError(
            "Preflight and observation discovery "
            "disagree about pending orders."
        )

    requirements, observations = (
        collect_required_observations(
            execution_session=execution_session,
            clock=clock,
        )
    )

    if requirements != initial_requirements:
        raise Model2GuardedExecutionError(
            "Trading requirements changed before "
            "collection completed."
        )

    if set(observations) != set(
        requirements.tickers
    ):
        raise Model2GuardedExecutionError(
            "Validated observation set is incomplete."
        )

    provenance_ids: dict[str, str] = {}

    for ticker in requirements.tickers:
        provenance = (
            record_model2_execution_observation(
                observations[ticker],
                now=clock(),
            )
        )

        provenance_ids[ticker] = (
            provenance.execution_run_id
        )

    pending_after_collection = (
        inspect_execution_prerequisites(
            execution_session=execution_session,
            now=clock(),
        )
    )

    if (
        pending_after_collection
        != expected_order_ids
    ):
        raise Model2GuardedExecutionError(
            "Pending-order state changed after "
            "observation collection."
        )

    current = discover_requirements(
        model2_database,
        execution_session,
    )

    if current.order_ids != expected_order_ids:
        raise Model2GuardedExecutionError(
            "Pending-order state changed before "
            "execution."
        )

    return (
        requirements,
        observations,
        provenance_ids,
    )


def _record_risk_rejection(
    *,
    database: Path,
    order_id: str,
    reason: str,
    rejected_at: datetime,
) -> GuardedRejectionResult:
    """
    Atomically convert one still-PENDING order into
    REJECTED after a deterministic execution-time
    risk rejection.

    This function never creates a fill or an execution
    attempt.
    """

    if (
        rejected_at.tzinfo is None
        or rejected_at.utcoffset() is None
    ):
        raise Model2GuardedExecutionError(
            "Rejection time must be timezone-aware."
        )

    uri = database.as_uri() + "?mode=rw"

    connection = sqlite3.connect(
        uri,
        uri=True,
        isolation_level=None,
        timeout=15,
    )

    try:
        connection.execute(
            "PRAGMA foreign_keys = ON"
        )

        connection.execute(
            "PRAGMA busy_timeout = 15000"
        )

        connection.execute(
            "BEGIN IMMEDIATE"
        )

        row = connection.execute(
            """
            SELECT
                ticker,
                status,
                model_version
            FROM paper_orders
            WHERE order_id = ?
            """,
            (order_id,),
        ).fetchone()

        if row is None:
            raise Model2GuardedExecutionError(
                f"Order disappeared before rejection: "
                f"{order_id}"
            )

        ticker, status, model_version = row

        if status != "PENDING":
            raise Model2GuardedExecutionError(
                "Risk-rejected order is no longer "
                f"PENDING: {order_id}"
            )

        if model_version != MODEL_2_VERSION:
            raise Model2GuardedExecutionError(
                "Risk-rejected order belongs to "
                "another model."
            )

        fill_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM paper_fills
            WHERE order_id = ?
            """,
            (order_id,),
        ).fetchone()[0]

        attempt_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM execution_attempts
            WHERE order_id = ?
            """,
            (order_id,),
        ).fetchone()[0]

        rejection_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM order_rejections
            WHERE order_id = ?
            """,
            (order_id,),
        ).fetchone()[0]

        if fill_count != 0:
            raise Model2GuardedExecutionError(
                "Cannot reject an order that already "
                "has a fill."
            )

        if attempt_count != 0:
            raise Model2GuardedExecutionError(
                "Cannot administratively record risk "
                "rejection after execution history "
                "already exists."
            )

        if rejection_count != 0:
            raise Model2GuardedExecutionError(
                "Order already has a rejection record."
            )

        rejected_at_utc = (
            rejected_at
            .astimezone(timezone.utc)
            .isoformat()
        )

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
                RISK_REJECTION_CODE,
                reason,
                rejected_at_utc,
            ),
        )

        changed = connection.execute(
            """
            UPDATE paper_orders
            SET status = 'REJECTED'
            WHERE order_id = ?
              AND status = 'PENDING'
              AND model_version = ?
            """,
            (
                order_id,
                MODEL_2_VERSION,
            ),
        )

        if changed.rowcount != 1:
            raise Model2GuardedExecutionError(
                "Could not transition exactly one "
                "risk-rejected order."
            )

        connection.execute("COMMIT")

        return GuardedRejectionResult(
            order_id=order_id,
            ticker=ticker,
            rejection_code=RISK_REJECTION_CODE,
            rejection_reason=reason,
        )

    except BaseException:
        if connection.in_transaction:
            connection.execute("ROLLBACK")

        raise

    finally:
        connection.close()


def run_guarded_execution(
    *,
    execution_session: date,
    confirmation: str,
    clock: Callable[[], datetime] | None = None,
) -> GuardedExecutionResult:
    """
    Backward-compatible single-order execution path.
    """

    if confirmation != CONFIRMATION_TEXT:
        raise Model2GuardedExecutionError(
            "Explicit paper-execution confirmation "
            "was not provided."
        )

    if clock is None:
        clock = lambda: datetime.now(timezone.utc)

    (
        model2_database,
        _,
        _,
    ) = _resolve_databases()

    pending = inspect_execution_prerequisites(
        execution_session=execution_session,
        now=clock(),
    )

    if len(pending) != 1:
        raise Model2GuardedExecutionError(
            "Single-order guarded execution requires "
            "exactly one pending order; "
            f"found {len(pending)}."
        )

    order_id = pending[0]

    (
        _,
        observations,
        provenance_ids,
    ) = _prepare_observations(
        execution_session=execution_session,
        expected_order_ids=pending,
        model2_database=model2_database,
        clock=clock,
    )

    current = discover_requirements(
        model2_database,
        execution_session,
    )

    ticker = _load_ticker(
        model2_database,
        order_id,
    )

    if ticker not in observations:
        raise Model2GuardedExecutionError(
            "No validated execution observation "
            f"exists for {ticker}."
        )

    holding_observations = {}

    for holding_ticker in current.holding_tickers:
        if holding_ticker not in observations:
            raise Model2GuardedExecutionError(
                "Missing validated holding price: "
                f"{holding_ticker}."
            )

        holding_observations[
            holding_ticker
        ] = observations[holding_ticker]

    result = execute_model2_order(
        order_id=order_id,
        execution_observation=observations[ticker],
        holding_observations=holding_observations,
        clock=clock,
    )

    expected_run_id = provenance_ids[ticker]

    if (
        result.execution_run_id
        != expected_run_id
    ):
        raise Model2GuardedExecutionError(
            "Committed execution lineage does not "
            "match the recorded observation."
        )

    return GuardedExecutionResult(
        order_id=result.order_id,
        ticker=ticker,
        fill_id=result.fill_id,
        execution_run_id=(
            result.execution_run_id
        ),
        reference_price=result.reference_price,
        fill_price=result.fill_price,
    )


def run_guarded_execution_batch(
    *,
    execution_session: date,
    confirmation: str,
    clock: Callable[[], datetime] | None = None,
) -> GuardedBatchExecutionResult:
    """
    Execute one or more pending Model 2 PAPER orders.

    A deterministic execution-time risk rejection is
    recorded as REJECTED and the batch continues.

    Infrastructure, data, provenance, database, timing,
    or other unexpected failures stop the batch.
    """

    if confirmation != CONFIRMATION_TEXT:
        raise Model2GuardedExecutionError(
            "Explicit paper-execution confirmation "
            "was not provided."
        )

    if clock is None:
        clock = lambda: datetime.now(timezone.utc)

    (
        model2_database,
        _,
        _,
    ) = _resolve_databases()

    initial_pending = (
        inspect_execution_prerequisites(
            execution_session=execution_session,
            now=clock(),
        )
    )

    if not initial_pending:
        raise Model2GuardedExecutionError(
            "No eligible pending Model 2 orders "
            "were found."
        )

    (
        _,
        observations,
        provenance_ids,
    ) = _prepare_observations(
        execution_session=execution_session,
        expected_order_ids=initial_pending,
        model2_database=model2_database,
        clock=clock,
    )

    completed: list[
        GuardedExecutionResult
    ] = []

    rejected: list[
        GuardedRejectionResult
    ] = []

    for index, order_id in enumerate(
        initial_pending
    ):
        expected_remaining = tuple(
            initial_pending[index:]
        )

        pending_now = (
            inspect_execution_prerequisites(
                execution_session=execution_session,
                now=clock(),
            )
        )

        if pending_now != expected_remaining:
            raise Model2GuardedExecutionError(
                "Pending-order state changed during "
                "batch execution. "
                f"Expected {expected_remaining}; "
                f"found {pending_now}."
            )

        current = discover_requirements(
            model2_database,
            execution_session,
        )

        if (
            current.order_ids
            != expected_remaining
        ):
            raise Model2GuardedExecutionError(
                "Trading requirements changed during "
                "batch execution."
            )

        ticker = _load_ticker(
            model2_database,
            order_id,
        )

        if ticker not in observations:
            raise Model2GuardedExecutionError(
                "No validated execution observation "
                f"exists for {ticker}."
            )

        holding_observations = {}

        for holding_ticker in (
            current.holding_tickers
        ):
            if holding_ticker not in observations:
                raise Model2GuardedExecutionError(
                    "Missing validated holding price: "
                    f"{holding_ticker}."
                )

            holding_observations[
                holding_ticker
            ] = observations[holding_ticker]

        try:
            result = execute_model2_order(
                order_id=order_id,
                execution_observation=(
                    observations[ticker]
                ),
                holding_observations=(
                    holding_observations
                ),
                clock=clock,
            )

        except Model2ProductionExecutionError as exc:
            message = str(exc)

            # Only a deterministic risk-engine rejection
            # becomes a terminal trading rejection.
            #
            # Everything else may represent stale data,
            # provenance problems, database failures,
            # timing errors, or another infrastructure
            # problem and therefore stops the batch.
            if not message.startswith(
                RISK_REJECTION_PREFIX
            ):
                raise

            reason = (
                "Execution-time Model 2 risk rejection: "
                + message[
                    len(RISK_REJECTION_PREFIX):
                ].strip()
            )

            rejection = _record_risk_rejection(
                database=model2_database,
                order_id=order_id,
                reason=reason,
                rejected_at=clock(),
            )

            rejected.append(rejection)

            continue

        expected_run_id = (
            provenance_ids[ticker]
        )

        if (
            result.execution_run_id
            != expected_run_id
        ):
            raise Model2GuardedExecutionError(
                "Committed execution lineage does not "
                "match the recorded observation."
            )

        completed.append(
            GuardedExecutionResult(
                order_id=result.order_id,
                ticker=ticker,
                fill_id=result.fill_id,
                execution_run_id=(
                    result.execution_run_id
                ),
                reference_price=(
                    result.reference_price
                ),
                fill_price=result.fill_price,
            )
        )

    final_pending = (
        inspect_execution_prerequisites(
            execution_session=execution_session,
            now=clock(),
        )
    )

    if final_pending:
        raise Model2GuardedExecutionError(
            "Batch completed but pending orders "
            f"remain: {final_pending}."
        )

    return GuardedBatchExecutionResult(
        results=tuple(completed),
        rejections=tuple(rejected),
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Guarded Model 2 PAPER execution. "
            "Executes one or more eligible orders "
            "sequentially."
        )
    )

    parser.add_argument(
        "--session",
        required=True,
        type=date.fromisoformat,
        help="Execution session YYYY-MM-DD.",
    )

    parser.add_argument(
        "--execute-paper",
        action="store_true",
        help=(
            "Explicitly request Model 2 "
            "paper execution."
        ),
    )

    parser.add_argument(
        "--confirm",
        default="",
        help="Must equal MODEL2-PAPER.",
    )

    args = parser.parse_args()

    if not args.execute_paper:
        print(
            "MODEL 2 GUARDED EXECUTION: NOT ARMED"
        )
        print(
            "No collection or execution was performed."
        )
        print()
        print(
            "To execute Model 2 paper orders, "
            "--execute-paper and the explicit "
            "confirmation token are both required."
        )

        return 0

    try:
        result = run_guarded_execution_batch(
            execution_session=args.session,
            confirmation=args.confirm,
        )

    except Exception as exc:
        print(
            "MODEL 2 GUARDED EXECUTION: BLOCKED",
            file=sys.stderr,
        )

        print(
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )

        print(
            "Do not retry blindly. Inspect the "
            "reported blocker first.",
            file=sys.stderr,
        )

        return 1

    print(
        "MODEL 2 PAPER EXECUTION BATCH: COMPLETED"
    )
    print(
        "========================================"
    )

    print(
        f"Orders filled: {result.filled_count}"
    )

    print(
        f"Orders risk-rejected: "
        f"{result.rejected_count}"
    )

    for number, item in enumerate(
        result.results,
        start=1,
    ):
        print()
        print(
            f"FILLED [{number}] "
            f"{item.order_id}"
        )
        print(
            f"Ticker: {item.ticker}"
        )
        print(
            "Reference price: "
            f"{item.reference_price}"
        )
        print(
            f"Fill price: {item.fill_price}"
        )
        print(
            f"Fill ID: {item.fill_id}"
        )
        print(
            "Execution lineage: "
            f"{item.execution_run_id}"
        )

    for number, item in enumerate(
        result.rejections,
        start=1,
    ):
        print()
        print(
            f"REJECTED [{number}] "
            f"{item.order_id}"
        )
        print(
            f"Ticker: {item.ticker}"
        )
        print(
            "Rejection code: "
            f"{item.rejection_code}"
        )
        print(
            "Reason: "
            f"{item.rejection_reason}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())