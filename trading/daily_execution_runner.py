from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Mapping

from database.pending_order_query import (
    PendingOrderQuery,
    PendingOrderReference,
)
from trading.pending_execution_batch_runner import (
    PendingExecutionBatchResult,
    PendingExecutionBatchRunner,
)


class DailyExecutionRunnerError(Exception):
    """
    Base exception for daily execution-runner failures.
    """


@dataclass(frozen=True)
class DailyExecutionResult:
    """
    Result of one complete execution-session run.
    """

    execution_session: date

    discovered_orders: tuple[
        PendingOrderReference,
        ...,
    ]

    batch_result: (
        PendingExecutionBatchResult
        | None
    )

    @property
    def discovered_order_count(
        self,
    ) -> int:

        return len(
            self.discovered_orders
        )

    @property
    def had_work(
        self,
    ) -> bool:

        return (
            self.discovered_order_count
            > 0
        )

    @property
    def filled_orders(
        self,
    ) -> int:

        if self.batch_result is None:
            return 0

        return (
            self.batch_result
            .filled_orders
        )

    @property
    def rejected_orders(
        self,
    ) -> int:

        if self.batch_result is None:
            return 0

        return (
            self.batch_result
            .rejected_orders
        )

    @property
    def failed_orders(
        self,
    ) -> int:

        if self.batch_result is None:
            return 0

        return (
            self.batch_result
            .failed_orders
        )

    @property
    def skipped_orders(
        self,
    ) -> int:

        if self.batch_result is None:
            return 0

        return (
            self.batch_result
            .skipped_orders
        )


class DailyExecutionRunner:
    """
    Top-level execution-session coordinator.

    The caller supplies only the target execution
    session and optional shared valuation inputs.

    Flow:

        execution_session
              ↓
        PendingOrderQuery
              ↓
        discover due PENDING orders
              ↓
        no work?
          │        │
         yes      no
          │        │
          ▼        ▼
        return   PendingExecutionBatchRunner
                       ↓
             FILLED / REJECTED /
               FAILED / SKIPPED

    This class does not fetch market data itself and
    does not execute orders directly.

    Those responsibilities remain delegated to the
    existing execution batch and orchestrator layers.
    """

    def __init__(
        self,
        pending_order_query: (
            PendingOrderQuery
        ),
        execution_batch_runner: (
            PendingExecutionBatchRunner
        ),
    ) -> None:

        self.pending_order_query = (
            pending_order_query
        )

        self.execution_batch_runner = (
            execution_batch_runner
        )

    def run(
        self,
        execution_session: date,

        execution_market_prices: (
            Mapping[
                str,
                object,
            ]
            | None
        ) = None,

        valuation_prices: (
            Mapping[
                str,
                object,
            ]
            | None
        ) = None,

        recorded_at_utc: (
            datetime | None
        ) = None,

    ) -> DailyExecutionResult:
        """
        Discover and process all pending orders due
        for one execution session.
        """

        if not isinstance(
            execution_session,
            date,
        ):
            raise TypeError(
                "execution_session must be "
                "a datetime.date."
            )

        # ---------------------------------------------
        # 1. DISCOVER
        # ---------------------------------------------

        discovered_orders = (
            self.pending_order_query
            .find_for_session(
                execution_session
            )
        )

        # ---------------------------------------------
        # 2. NO WORK IS A VALID RESULT
        # ---------------------------------------------

        if not discovered_orders:

            return DailyExecutionResult(
                execution_session=(
                    execution_session
                ),
                discovered_orders=(),
                batch_result=None,
            )

        order_ids = tuple(
            order.order_id
            for order
            in discovered_orders
        )

        # ---------------------------------------------
        # 3. EXECUTION BATCH
        # ---------------------------------------------

        batch_result = (
            self.execution_batch_runner
            .run(
                order_ids=order_ids,
                execution_session=(
                    execution_session
                ),
                execution_market_prices=(
                    execution_market_prices
                ),
                valuation_prices=(
                    valuation_prices
                ),
                recorded_at_utc=(
                    recorded_at_utc
                ),
            )
        )

        return DailyExecutionResult(
            execution_session=(
                execution_session
            ),
            discovered_orders=(
                discovered_orders
            ),
            batch_result=(
                batch_result
            ),
        )