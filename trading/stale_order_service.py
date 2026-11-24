from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol

from trading.execution_readiness import (
    ExecutionReadinessChecker,
    ExecutionReadinessResult,
)


MISSED_EXECUTION_WINDOW_CODE = (
    "MISSED_EXECUTION_WINDOW"
)

MISSED_EXECUTION_WINDOW_REASON = (
    "The allowed near-open execution "
    "window expired before execution occurred."
)


class StaleOrderError(Exception):
    """
    Base error for stale-order processing.
    """


class StaleOrderSafetyError(
    StaleOrderError
):
    """
    Raised when stale-order mutation would
    not be safe.
    """


class PendingOrderQueryLike(
    Protocol
):

    def find_order_ids_for_session(
        self,
        execution_session: date,
    ) -> list[str]:
        ...


class TradingStorageLike(
    Protocol
):

    def reject_order(
        self,
        order_id: str,
        rejection_code: str,
        rejection_reason: str,
    ):
        ...


@dataclass(frozen=True)
class StaleOrderResult:

    execution_session: date

    discovered_orders: int
    rejected_orders: int

    rejection_code: str | None
    rejection_reason: str | None

    readiness: ExecutionReadinessResult


class StaleOrderService:
    """
    Explicitly expires PENDING orders whose
    allowed near-open execution window has passed.

    Safety rules:
        - never acts before market open
        - never acts while execution window is open
        - never acts if pending-order audit has problems
        - never invents an execution price
        - never creates fills
        - never moves an order to another session
        - only rejects currently PENDING orders returned
          by PendingOrderQuery
    """

    def __init__(
        self,
        readiness_checker:
        ExecutionReadinessChecker,
        pending_order_query:
        PendingOrderQueryLike,
        trading_storage:
        TradingStorageLike,
    ) -> None:

        self.readiness_checker = (
            readiness_checker
        )

        self.pending_order_query = (
            pending_order_query
        )

        self.trading_storage = (
            trading_storage
        )

    def expire_session(
        self,
        execution_session: date,
    ) -> StaleOrderResult:

        readiness = (
            self.readiness_checker
            .check(
                execution_session
            )
        )

        if (
            readiness.pending_orders
            == 0
        ):

            return StaleOrderResult(
                execution_session=(
                    execution_session
                ),
                discovered_orders=0,
                rejected_orders=0,
                rejection_code=None,
                rejection_reason=None,
                readiness=readiness,
            )

        if (
            readiness.problem_orders
            > 0
        ):

            raise StaleOrderSafetyError(
                "Cannot expire orders because "
                "the pending-order audit found "
                f"{readiness.problem_orders} "
                "problem order(s)."
            )

        if (
            readiness.checked_at_utc
            < readiness.market_open_utc
        ):

            raise StaleOrderSafetyError(
                "Cannot expire orders before "
                "the execution session opens."
            )

        if (
            readiness.execution_window_open
        ):

            raise StaleOrderSafetyError(
                "Cannot expire orders while "
                "the execution window is open."
            )

        if (
            readiness.checked_at_utc
            <= readiness.window_close_utc
        ):

            raise StaleOrderSafetyError(
                "Cannot expire orders before "
                "the execution window has expired."
            )

        order_ids = tuple(
            self.pending_order_query
            .find_order_ids_for_session(
                execution_session
            )
        )

        if (
            len(
                order_ids
            )
            != readiness.pending_orders
        ):

            raise StaleOrderSafetyError(
                "Pending-order count changed "
                "between readiness validation "
                "and stale-order processing."
            )

        rejected = 0

        for order_id in order_ids:

            self.trading_storage.reject_order(
                order_id=order_id,
                rejection_code=(
                    MISSED_EXECUTION_WINDOW_CODE
                ),
                rejection_reason=(
                    MISSED_EXECUTION_WINDOW_REASON
                ),
            )

            rejected += 1

        return StaleOrderResult(
            execution_session=(
                execution_session
            ),
            discovered_orders=(
                len(
                    order_ids
                )
            ),
            rejected_orders=(
                rejected
            ),
            rejection_code=(
                MISSED_EXECUTION_WINDOW_CODE
            ),
            rejection_reason=(
                MISSED_EXECUTION_WINDOW_REASON
            ),
            readiness=readiness,
        )