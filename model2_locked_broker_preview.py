
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Callable

from model2_config import MODEL_2_VERSION, get_model2_paths
from model2_execution_risk import assess_model2_execution_risk
from model2_locked_observation_verification import (
    verify_locked_model2_observation,
)
from model2_locked_portfolio import locked_test_model2_portfolio
from risk.risk_engine import RiskDecision
from trading.flexible_execution_observation import (
    FlexibleExecutionObservation,
)
from trading.orders import Fill, Order, OrderSide
from trading.paper_broker import BrokerConfig, PaperBroker


class Model2LockedBrokerPreviewError(RuntimeError):
    """A verified, risk-approved broker preview is unavailable."""


@dataclass(frozen=True)
class Model2LockedBrokerPreviewResult:
    order_id: str
    execution_run_id: str
    fill: Fill
    cash_before: Decimal
    cash_after: Decimal
    checked_at_utc: datetime


def _utc(value: datetime) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise Model2LockedBrokerPreviewError(
            "Clock must return a timezone-aware datetime."
        )

    return value.astimezone(timezone.utc)


def preview_locked_model2_broker(
    *,
    database_path: str | Path,
    order_id: str,
    execution_observation: FlexibleExecutionObservation,
    holding_observations: dict[
        str, FlexibleExecutionObservation
    ],
    clock: Callable[[], datetime],
    broker_config: BrokerConfig | None = None,
) -> Model2LockedBrokerPreviewResult:
    """
    TEST-ONLY broker preview.

    The database transaction is always rolled back.

    The broker modifies only the reconstructed,
    in-memory portfolio. No fill or attempt is saved.
    """
    paths = get_model2_paths()
    source_database = Path(
        paths.observation_database
    ).expanduser().resolve()

    with locked_test_model2_portfolio(
        database_path
    ) as (connection, portfolio):

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
            raise Model2LockedBrokerPreviewError(
                "Order does not exist."
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

        if status != "PENDING":
            raise Model2LockedBrokerPreviewError(
                f"Order is {status}, not PENDING."
            )

        if model_version != MODEL_2_VERSION:
            raise Model2LockedBrokerPreviewError(
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
            raise Model2LockedBrokerPreviewError(
                "Order already has a fill."
            )

        # A missing attempts table is not proof that
        # the order has never been attempted.
        attempts_table = connection.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table'
              AND name = 'execution_attempts'
            """
        ).fetchone()

        if attempts_table is None:
            raise Model2LockedBrokerPreviewError(
                "Execution-attempt table must be "
                "initialized in the temporary database."
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
            raise Model2LockedBrokerPreviewError(
                "Order has an attempt requiring review."
            )

        try:
            order = Order(
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
            raise Model2LockedBrokerPreviewError(
                "Stored order contains invalid fields."
            ) from exc

        now = _utc(clock())

        # Verify the actual source bar and its recorded
        # Model 2 lineage while the trading lock is held.
        execution_run_id = verify_locked_model2_observation(
            connection=connection,
            source_database=source_database,
            observation=execution_observation,
            now=now,
        )

        if (
            execution_observation.ticker != order.ticker
            or execution_observation.execution_session
            != order.execution_session
        ):
            raise Model2LockedBrokerPreviewError(
                "Execution observation does not match "
                "the pending order."
            )

        positions = set(portfolio.positions)

        if set(holding_observations) != positions:
            missing = positions - set(holding_observations)
            extra = set(holding_observations) - positions

            raise Model2LockedBrokerPreviewError(
                "Holding observation set does not match "
                f"the portfolio. Missing: {sorted(missing)}; "
                f"unexpected: {sorted(extra)}."
            )

        valuation_prices = {}

        for holding_ticker in sorted(positions):
            holding_observation = holding_observations[
                holding_ticker
            ]

            verify_locked_model2_observation(
                connection=connection,
                source_database=source_database,
                observation=holding_observation,
                now=now,
            )

            if (
                holding_observation.ticker != holding_ticker
                or holding_observation.execution_session
                != order.execution_session
            ):
                raise Model2LockedBrokerPreviewError(
                    "Holding observation does not match "
                    f"{holding_ticker} or the order session."
                )

            valuation_prices[holding_ticker] = (
                holding_observation.reference_price
            )

        config = (
            broker_config
            if broker_config is not None
            else BrokerConfig()
        )

        cash_before = portfolio.cash

        risk = assess_model2_execution_risk(
            order=order,
            observation=execution_observation,
            portfolio=portfolio,
            market_prices=valuation_prices,
            clock=lambda: now,
            broker_config=config,
        )

        if risk.assessment.decision != RiskDecision.APPROVE:
            reasons = "; ".join(
                issue.message
                for issue in risk.assessment.issues
            )

            raise Model2LockedBrokerPreviewError(
                "Execution-time risk did not approve "
                f"the trade: {reasons}"
            )

        broker = PaperBroker(
            portfolio=portfolio,
            config=config,
        )

        # The Close is a paper-execution price proxy,
        # not a verified executable market quote.
        fill = broker.execute(
            order=order,
            market_price=risk.reference_price,
            actual_session=order.execution_session,
        )

        if (
            fill.fill_price != risk.projected_fill_price
            or fill.reference_price != risk.reference_price
        ):
            raise Model2LockedBrokerPreviewError(
                "Broker fill disagrees with the "
                "risk-approved price."
            )

        return Model2LockedBrokerPreviewResult(
            order_id=order.order_id,
            execution_run_id=execution_run_id,
            fill=fill,
            cash_before=cash_before,
            cash_after=portfolio.cash,
            checked_at_utc=now,
        )