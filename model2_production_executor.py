from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable
from uuid import uuid4

from model2_config import (
    MODEL_2_VERSION,
    get_model2_paths,
)
from model2_execution_readiness import check_execution_window
from model2_execution_risk import assess_model2_execution_risk
from model2_production_observation_verification import (
    verify_production_model2_observation,
)
from model2_locked_portfolio import _rebuild_with_connection
from risk.risk_engine import RiskDecision
from trading.flexible_execution_observation import (
    FlexibleExecutionObservation,
)
from trading.orders import (
    Order,
    OrderSide,
    OrderStatus,
)
from trading.paper_broker import (
    BrokerConfig,
    PaperBroker,
)


class Model2ProductionExecutionError(RuntimeError):
    """A guarded Model 2 paper execution could not proceed."""


@dataclass(frozen=True)
class Model2ProductionExecutionResult:
    order_id: str
    fill_id: str
    attempt_id: str
    execution_run_id: str
    reference_price: str
    fill_price: str
    started_at_utc: datetime
    completed_at_utc: datetime


def _utc(value: datetime) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise Model2ProductionExecutionError(
            "Clock must return a timezone-aware datetime."
        )

    return value.astimezone(timezone.utc)


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(
        value.replace("Z", "+00:00")
    )

    if parsed.tzinfo is None:
        raise ValueError(
            "Stored datetime is not timezone aware."
        )

    return parsed.astimezone(timezone.utc)


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
        raise Model2ProductionExecutionError(
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

    if model_version != MODEL_2_VERSION:
        raise Model2ProductionExecutionError(
            "Order belongs to another model."
        )

    if status != OrderStatus.PENDING.value:
        raise Model2ProductionExecutionError(
            f"Order is {status}, not PENDING."
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
        raise Model2ProductionExecutionError(
            "Pending order already has a fill."
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
        raise Model2ProductionExecutionError(
            "execution_attempts table is missing."
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
        raise Model2ProductionExecutionError(
            "Order already has execution history."
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
        raise Model2ProductionExecutionError(
            "Order has a rejection record."
        )

    try:
        return Order(
            order_id=stored_id,
            ticker=ticker,
            side=OrderSide(side),
            quantity=quantity,
            signal_timestamp_utc=_parse_datetime(
                signal_text
            ),
            execution_session=date.fromisoformat(
                session_text
            ),
        )

    except (TypeError, ValueError) as exc:
        raise Model2ProductionExecutionError(
            "Stored order contains invalid fields."
        ) from exc


def execute_model2_order(
    *,
    order_id: str,
    execution_observation: FlexibleExecutionObservation,
    holding_observations: dict[
        str,
        FlexibleExecutionObservation,
    ],
    clock: Callable[[], datetime] | None = None,
    broker_config: BrokerConfig | None = None,
) -> Model2ProductionExecutionResult:
    """
    Execute exactly one Model 2 PAPER order.

    This function:
      - operates only on the configured Model 2 database,
      - keeps one SQLite write lock for the entire trade,
      - verifies source observations and provenance,
      - rebuilds the portfolio while locked,
      - performs execution-time risk assessment,
      - lets PaperBroker create the fill,
      - atomically persists attempt/fill/lineage/status.

    It never initializes schemas.
    """

    if clock is None:
        clock = lambda: datetime.now(timezone.utc)

    paths = get_model2_paths()

    trading_database = Path(
        paths.model2_database
    ).expanduser().resolve()

    model1_database = Path(
        paths.model1_database
    ).expanduser().resolve()

    source_database = Path(
        paths.observation_database
    ).expanduser().resolve()

    if trading_database == model1_database:
        raise Model2ProductionExecutionError(
            "Model 2 database resolves to Model 1 database."
        )

    if trading_database == source_database:
        raise Model2ProductionExecutionError(
            "Trading and observation databases are not isolated."
        )

    if not trading_database.is_file():
        raise Model2ProductionExecutionError(
            "Configured Model 2 database does not exist."
        )

    if not source_database.is_file():
        raise Model2ProductionExecutionError(
            "Observation database does not exist."
        )

    config = (
        broker_config
        if broker_config is not None
        else BrokerConfig()
    )

    connection = sqlite3.connect(
        trading_database.as_uri() + "?mode=rw",
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

        if (
            execution_observation.ticker
            != order.ticker
        ):
            raise Model2ProductionExecutionError(
                "Execution observation ticker does not "
                "match the order."
            )

        if (
            execution_observation.execution_session
            != order.execution_session
        ):
            raise Model2ProductionExecutionError(
                "Execution observation session does not "
                "match the order."
            )

        execution_run_id = (
            verify_production_model2_observation(
                connection=connection,
                source_database=source_database,
                observation=execution_observation,
                now=started_at,
            )
        )

        position_tickers = set(
            portfolio.positions
        )

        supplied_holding_tickers = set(
            holding_observations
        )

        if (
            supplied_holding_tickers
            != position_tickers
        ):
            missing = (
                position_tickers
                - supplied_holding_tickers
            )

            extra = (
                supplied_holding_tickers
                - position_tickers
            )

            raise Model2ProductionExecutionError(
                "Holding observations do not match "
                f"the locked portfolio. Missing: "
                f"{sorted(missing)}; unexpected: "
                f"{sorted(extra)}."
            )

        market_prices = {}

        for ticker in sorted(position_tickers):
            observation = (
                holding_observations[ticker]
            )

            if observation.ticker != ticker:
                raise Model2ProductionExecutionError(
                    "Holding observation ticker "
                    f"mismatch: {ticker}."
                )

            if (
                observation.execution_session
                != order.execution_session
            ):
                raise Model2ProductionExecutionError(
                    "Holding observation session "
                    f"mismatch: {ticker}."
                )

            verify_production_model2_observation(
                connection=connection,
                source_database=source_database,
                observation=observation,
                now=started_at,
            )

            market_prices[ticker] = (
                observation.reference_price
            )

        risk = assess_model2_execution_risk(
            order=order,
            observation=execution_observation,
            portfolio=portfolio,
            market_prices=market_prices,
            clock=lambda: started_at,
            broker_config=config,
        )

        if (
            risk.assessment.decision
            != RiskDecision.APPROVE
        ):
            messages = []

            for issue in getattr(
                risk.assessment,
                "issues",
                (),
            ):
                message = getattr(
                    issue,
                    "message",
                    str(issue),
                )

                messages.append(message)

            details = (
                "; ".join(messages)
                if messages
                else "risk engine rejected trade"
            )

            raise Model2ProductionExecutionError(
                "Execution-time risk rejected "
                f"the trade: {details}"
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
            fill.reference_price
            != risk.reference_price
        ):
            raise Model2ProductionExecutionError(
                "Broker reference price differs "
                "from the approved price."
            )

        if (
            fill.fill_price
            != risk.projected_fill_price
        ):
            raise Model2ProductionExecutionError(
                "Broker fill price differs from "
                "the risk-approved projected fill."
            )

        if fill.status != OrderStatus.FILLED:
            raise Model2ProductionExecutionError(
                "PaperBroker did not return a FILLED fill."
            )

        fill_id = str(uuid4())
        attempt_id = str(uuid4())

        created_at = started_at.isoformat()

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
                created_at,
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
                created_at,
            ),
        )

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
            raise Model2ProductionExecutionError(
                "Order status changed before commit."
            )

        completed_at = _utc(clock())

        if completed_at < started_at:
            raise Model2ProductionExecutionError(
                "Clock moved backward during execution."
            )

        check_execution_window(
            order.execution_session,
            completed_at,
        )

        final_run_id = (
            verify_production_model2_observation(
                connection=connection,
                source_database=source_database,
                observation=execution_observation,
                now=completed_at,
            )
        )

        if (
            final_run_id
            != execution_run_id
        ):
            raise Model2ProductionExecutionError(
                "Execution provenance changed "
                "before commit."
            )

        for ticker in sorted(position_tickers):
            verify_production_model2_observation(
                connection=connection,
                source_database=source_database,
                observation=holding_observations[ticker],
                now=completed_at,
            )

        finalized = connection.execute(
            """
            UPDATE execution_attempts
            SET
                outcome = 'FILLED',
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
            raise Model2ProductionExecutionError(
                "Execution attempt could not "
                "be finalized."
            )

        connection.execute("COMMIT")

        return Model2ProductionExecutionResult(
            order_id=order.order_id,
            fill_id=fill_id,
            attempt_id=attempt_id,
            execution_run_id=execution_run_id,
            reference_price=str(
                fill.reference_price
            ),
            fill_price=str(
                fill.fill_price
            ),
            started_at_utc=started_at,
            completed_at_utc=completed_at,
        )

    except BaseException:
        if connection.in_transaction:
            connection.execute("ROLLBACK")

        raise

    finally:
        connection.close()