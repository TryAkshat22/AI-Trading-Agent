
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Callable

from model2_config import MODEL_2_VERSION
from model2_execution_risk import (
    Model2ExecutionRiskResult,
    assess_model2_execution_risk,
)
from model2_locked_portfolio import (
    locked_test_model2_portfolio,
)
from risk.risk_engine import RiskDecision
from trading.flexible_execution_observation import (
    FlexibleExecutionObservation,
)
from trading.orders import Order, OrderSide
from trading.portfolio import money


class Model2LockedPreviewError(RuntimeError):
    """A locked execution preview cannot proceed safely."""


@dataclass(frozen=True)
class Model2LockedPreviewResult:
    order_id: str
    risk: Model2ExecutionRiskResult
    starting_cash: Decimal
    existing_positions: tuple[str, ...]
    checked_at_utc: datetime


def _utc(value: datetime, field: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise Model2LockedPreviewError(
            f"{field} must be timezone-aware."
        )

    return value.astimezone(timezone.utc)


def _validate_holding_observation(
    *,
    ticker: str,
    observation: FlexibleExecutionObservation,
    execution_session: date,
    now: datetime,
) -> Decimal:
    """
    Validate the timing and identity of an existing
    holding's supplied valuation observation.

    TEST-ONLY: This does not establish that the
    observation originated in the source database.
    The eventual executor must verify provenance.
    """
    if (
        observation.ticker != ticker
        or observation.execution_session != execution_session
        or observation.price_field != "Close"
        or observation.model != "flexible-observed-close-v1"
    ):
        raise Model2LockedPreviewError(
            f"Invalid valuation observation for {ticker}."
        )

    bar_start = _utc(
        observation.bar_start_utc,
        "bar_start_utc",
    )
    bar_end = _utc(
        observation.bar_end_utc,
        "bar_end_utc",
    )
    retrieved = _utc(
        observation.retrieved_at_utc,
        "retrieved_at_utc",
    )
    checked = _utc(
        observation.execution_checked_at_utc,
        "execution_checked_at_utc",
    )

    if (
        bar_end - bar_start != timedelta(minutes=1)
        or bar_end > retrieved
        or retrieved > checked
        or checked > now
        or now - bar_end > timedelta(minutes=5)
    ):
        raise Model2LockedPreviewError(
            f"Valuation observation for {ticker} "
            "is incomplete, stale, or from the future."
        )

    try:
        price = money(observation.reference_price)
    except (ValueError, TypeError, ArithmeticError) as exc:
        raise Model2LockedPreviewError(
            f"Invalid valuation price for {ticker}."
        ) from exc

    if not price.is_finite() or price <= 0:
        raise Model2LockedPreviewError(
            f"Invalid valuation price for {ticker}."
        )

    return price


def preview_locked_model2_execution(
    *,
    database_path: str | Path,
    order_id: str,
    execution_observation: FlexibleExecutionObservation,
    holding_observations: dict[
        str,
        FlexibleExecutionObservation,
    ],
    clock: Callable[[], datetime],
) -> Model2LockedPreviewResult:
    """
    TEST-ONLY calculation under one SQLite write lock.

    Reads a pending order and rebuilds the portfolio
    using the same database connection.

    Does not:
      - retrieve market data
      - persist an execution attempt
      - call the paper broker
      - create a fill or rejection
      - change an order's status
      - write a portfolio snapshot
    """
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
            raise Model2LockedPreviewError(
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

        if status != "PENDING":
            raise Model2LockedPreviewError(
                f"Order is {status}, not PENDING."
            )

        if model_version != MODEL_2_VERSION:
            raise Model2LockedPreviewError(
                "Order belongs to another model."
            )

        existing_fill = connection.execute(
            """
            SELECT 1
            FROM paper_fills
            WHERE order_id = ?
            """,
            (order_id,),
        ).fetchone()

        if existing_fill is not None:
            raise Model2LockedPreviewError(
                "Order already has a fill."
            )

        # The attempts table is optional in a temporary
        # database. If it exists, any previous attempt
        # requires reconciliation before proceeding.
        attempts_table = connection.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table'
              AND name = 'execution_attempts'
            """
        ).fetchone()

        if attempts_table is not None:
            existing_attempt = connection.execute(
                """
                SELECT 1
                FROM execution_attempts
                WHERE order_id = ?
                """,
                (order_id,),
            ).fetchone()

            if existing_attempt is not None:
                raise Model2LockedPreviewError(
                    "Order has an execution attempt "
                    "requiring review."
                )

        try:
            signal_time = datetime.fromisoformat(
                signal_text.replace("Z", "+00:00")
            )

            order = Order(
                order_id=stored_id,
                ticker=ticker,
                side=OrderSide(side),
                quantity=quantity,
                signal_timestamp_utc=signal_time,
                execution_session=date.fromisoformat(
                    session_text
                ),
            )
        except (ValueError, TypeError) as exc:
            raise Model2LockedPreviewError(
                "Stored order contains invalid fields."
            ) from exc

        now = _utc(clock(), "clock")

        existing_positions = tuple(
            sorted(portfolio.positions)
        )

        missing_prices = (
            set(existing_positions)
            - set(holding_observations)
        )

        if missing_prices:
            raise Model2LockedPreviewError(
                "Missing valuation observations for: "
                + ", ".join(sorted(missing_prices))
            )

        valuation_prices = {}

        for holding_ticker in existing_positions:
            valuation_prices[holding_ticker] = (
                _validate_holding_observation(
                    ticker=holding_ticker,
                    observation=holding_observations[
                        holding_ticker
                    ],
                    execution_session=order.execution_session,
                    now=now,
                )
            )

        # Risk is assessed before releasing the same
        # lock used to reconstruct the portfolio.
        risk_result = assess_model2_execution_risk(
            order=order,
            observation=execution_observation,
            portfolio=portfolio,
            market_prices=valuation_prices,
            clock=lambda: now,
        )

        if (
            risk_result.assessment.decision
            not in {
                RiskDecision.APPROVE,
                RiskDecision.REJECT,
            }
        ):
            raise Model2LockedPreviewError(
                "Risk engine returned an unknown decision."
            )

        return Model2LockedPreviewResult(
            order_id=stored_id,
            risk=risk_result,
            starting_cash=portfolio.cash,
            existing_positions=existing_positions,
            checked_at_utc=now,
        )