
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable
from uuid import uuid4

from model2_config import MODEL_2_VERSION, get_model2_paths
from model2_execution_readiness import check_execution_window
from model2_execution_risk import assess_model2_execution_risk
from model2_locked_observation_verification import (
    verify_locked_model2_observation,
)
from model2_locked_portfolio import (
    _rebuild_with_connection,
    _test_database_path,
)
from risk.risk_engine import RiskDecision
from trading.flexible_execution_observation import (
    FlexibleExecutionObservation,
)
from trading.orders import Order, OrderSide, OrderStatus
from trading.paper_broker import BrokerConfig, PaperBroker


class Model2IntegratedExecutionError(RuntimeError):
    """A test-only integrated execution could not proceed."""


@dataclass(frozen=True)
class Model2IntegratedExecutionResult:
    order_id: str
    fill_id: str
    attempt_id: str
    execution_run_id: str
    reference_price: str
    fill_price: str


def _utc(value: datetime) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise Model2IntegratedExecutionError(
            "Clock must return a timezone-aware datetime."
        )

    return value.astimezone(timezone.utc)


def _load_pending_order(
    connection: sqlite3.Connection,
    order_id: str,
) -> Order:
    row = connection.execute(
        """
        SELECT
            order_id,
            ticker,
            side,
            quantity,
            signal_timestamp_utc,
            execution_session,
            status,
            model_version
        FROM paper_orders
        WHERE order_id = ?
        """,
        (order_id,),
    ).fetchone()

    if row is None:
        raise Model2IntegratedExecutionError(
            f"Order does not exist: {order_id}"
        )

    (
        stored_id,
        ticker,
        side,
        quantity,
        signal_text,
        session_text,
        status,
        model_version,
    ) = row

    if status != OrderStatus.PENDING.value:
        raise Model2IntegratedExecutionError(
            f"Order is {status}, not PENDING."
        )

    if model_version != MODEL_2_VERSION:
        raise Model2IntegratedExecutionError(
            "Order belongs to another model."
        )

    prior_fill = connection.execute(
        """
        SELECT 1
        FROM paper_fills
        WHERE order_id = ?
        """,
        (order_id,),
    ).fetchone()

    if prior_fill is not None:
        raise Model2IntegratedExecutionError(
            "Order already has a fill."
        )

    attempts_table = connection.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table'
          AND name = 'execution_attempts'
        """
    ).fetchone()

    if attempts_table is None:
        raise Model2IntegratedExecutionError(
            "Execution-attempt table is missing."
        )

    prior_attempt = connection.execute(
        """
        SELECT 1
        FROM execution_attempts
        WHERE order_id = ?
        """,
        (order_id,),
    ).fetchone()

    if prior_attempt is not None:
        raise Model2IntegratedExecutionError(
            "Order has an execution attempt "
            "requiring review."
        )

    prior_rejection = connection.execute(
        """
        SELECT 1
        FROM order_rejections
        WHERE order_id = ?
        """,
        (order_id,),
    ).fetchone()

    if prior_rejection is not None:
        raise Model2IntegratedExecutionError(
            "Order has a rejection record."
        )

    try:
        return Order(
            order_id=stored_id,
            ticker=ticker,
            side=OrderSide(side),
            quantity=quantity,
            signal_timestamp_utc=datetime.fromisoformat(
                signal_text.replace("Z", "+00:00")
            ),
            execution_session=date.fromisoformat(
                session_text
            ),
        )
    except (TypeError, ValueError) as exc:
        raise Model2IntegratedExecutionError(
            "Stored order contains invalid fields."
        ) from exc


def execute_test_model2_order(
    *,
    database_path: str | Path,
    order_id: str,
    execution_observation: FlexibleExecutionObservation,
    holding_observations: dict[
        str, FlexibleExecutionObservation
    ],
    clock: Callable[[], datetime],
    broker_config: BrokerConfig | None = None,
    after_fill_insert: Callable[[], None] | None = None,
) -> Model2IntegratedExecutionResult:
    """
    TEST-ONLY integrated paper execution.

    Acquires one SQLite write lock and retains it
    through portfolio reconstruction, observation
    verification, risk assessment, broker execution,
    and the atomic commit.

    Refuses configured live databases.

    The failure hook exists only for rollback tests.
    """
    path = _test_database_path(database_path)

    paths = get_model2_paths()

    source_database = Path(
        paths.observation_database
    ).expanduser().resolve()

    if (
        not source_database.is_file()
        or source_database == path
    ):
        raise Model2IntegratedExecutionError(
            "Separate observation database is missing."
        )

    config = (
        broker_config
        if broker_config is not None
        else BrokerConfig()
    )

    connection = sqlite3.connect(
        path.as_uri() + "?mode=rw",
        uri=True,
        timeout=15,
        isolation_level=None,
    )

    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 15000")

        # Every read of trading state below occurs
        # after acquiring this write lock.
        connection.execute("BEGIN IMMEDIATE")

        order = _load_pending_order(
            connection,
            order_id,
        )

        started_at = _utc(clock())

        check_execution_window(
            order.execution_session,
            started_at,
        )

        portfolio = _rebuild_with_connection(
            connection
        )

        execution_run_id = (
            verify_locked_model2_observation(
                connection=connection,
                source_database=source_database,
                observation=execution_observation,
                now=started_at,
            )
        )

        if (
            execution_observation.ticker != order.ticker
            or execution_observation.execution_session
            != order.execution_session
        ):
            raise Model2IntegratedExecutionError(
                "Execution observation does not "
                "match the pending order."
            )

        positions = set(portfolio.positions)

        if set(holding_observations) != positions:
            missing = positions - set(holding_observations)
            extra = set(holding_observations) - positions

            raise Model2IntegratedExecutionError(
                "Holding observations do not match "
                f"the portfolio. Missing: {sorted(missing)}; "
                f"unexpected: {sorted(extra)}."
            )

        valuation_prices = {}

        for ticker in sorted(positions):
            observation = holding_observations[ticker]

            verify_locked_model2_observation(
                connection=connection,
                source_database=source_database,
                observation=observation,
                now=started_at,
            )

            if (
                observation.ticker != ticker
                or observation.execution_session
                != order.execution_session
            ):
                raise Model2IntegratedExecutionError(
                    f"Invalid holding observation: {ticker}"
                )

            valuation_prices[ticker] = (
                observation.reference_price
            )

        risk = assess_model2_execution_risk(
            order=order,
            observation=execution_observation,
            portfolio=portfolio,
            market_prices=valuation_prices,
            clock=lambda: started_at,
            broker_config=config,
        )

        if risk.assessment.decision != RiskDecision.APPROVE:
            reasons = "; ".join(
                issue.message
                for issue in risk.assessment.issues
            )

            raise Model2IntegratedExecutionError(
                "Execution-time risk rejected "
                f"the trade: {reasons}"
            )

        broker = PaperBroker(
            portfolio=portfolio,
            config=config,
        )

        fill = broker.execute(
            order=order,
            market_price=risk.reference_price,
            actual_session=order.execution_session,
        )

        if (
            fill.reference_price != risk.reference_price
            or fill.fill_price
            != risk.projected_fill_price
            or fill.status != OrderStatus.FILLED
        ):
            raise Model2IntegratedExecutionError(
                "Broker fill differs from "
                "the risk-approved trade."
            )

        # All persistence below uses this SAME
        # connection and its existing write lock.
        fill_id = str(uuid4())
        attempt_id = str(uuid4())

        recorded_at = started_at.isoformat()

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
            VALUES (
                ?, ?, ?, ?, 'STARTED',
                ?, NULL, NULL, NULL
            )
            """,
            (
                attempt_id,
                order.order_id,
                execution_run_id,
                execution_observation
                .retrieved_at_utc
                .astimezone(timezone.utc)
                .isoformat(),
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
                ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, NULL, ?
            )
            """,
            (
                fill_id,
                fill.order_id,
                fill.ticker,
                fill.side.value,
                fill.quantity,
                fill.execution_session.isoformat(),
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
                fill_id,
                execution_run_id
            )
            VALUES (?, ?)
            """,
            (
                fill_id,
                execution_run_id,
            ),
        )

        changed = connection.execute(
            """
            UPDATE paper_orders
            SET status = 'FILLED'
            WHERE order_id = ?
              AND status = 'PENDING'
              AND model_version = ?
            """,
            (
                order.order_id,
                MODEL_2_VERSION,
            ),
        )

        if changed.rowcount != 1:
            raise Model2IntegratedExecutionError(
                "Order status changed before commit."
            )

        # Time must be checked again AFTER all
        # potentially slow work and BEFORE COMMIT.
        completed_at = _utc(clock())

        check_execution_window(
            order.execution_session,
            completed_at,
        )

        # Recheck the actual source and its provenance
        # at the final time. A formerly fresh bar
        # cannot justify a later fill.
        final_run_id = (
            verify_locked_model2_observation(
                connection=connection,
                source_database=source_database,
                observation=execution_observation,
                now=completed_at,
            )
        )

        if final_run_id != execution_run_id:
            raise Model2IntegratedExecutionError(
                "Execution provenance changed "
                "before commit."
            )

        for ticker in sorted(positions):
            verify_locked_model2_observation(
                connection=connection,
                source_database=source_database,
                observation=holding_observations[ticker],
                now=completed_at,
            )

        finalized = connection.execute(
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

        if finalized.rowcount != 1:
            raise Model2IntegratedExecutionError(
                "Execution attempt could not "
                "be finalized."
            )

        connection.execute("COMMIT")

        return Model2IntegratedExecutionResult(
            order_id=order.order_id,
            fill_id=fill_id,
            attempt_id=attempt_id,
            execution_run_id=execution_run_id,
            reference_price=str(fill.reference_price),
            fill_price=str(fill.fill_price),
        )

    except BaseException:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        raise

    finally:
        connection.close()