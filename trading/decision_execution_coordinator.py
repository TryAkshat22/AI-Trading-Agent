
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from trading.decision_pipeline import (
    DecisionStatus,
    TradeDecision,
)
from trading.decision_timestamp import (
    DecisionTimestampValidator,
    ValidatedDecisionTimestamp,
)
from trading.execution_service import (
    ExecutionService,
    PreparedOrder,
)
from trading.orders import OrderSide


class DecisionExecutionCoordinatorError(Exception):
    """Base exception for decision-to-order coordination failures."""


class MissingDecisionSourceSessionError(
    DecisionExecutionCoordinatorError
):
    """An actionable decision has no completed source session."""


class MissingDecisionRunIdError(
    DecisionExecutionCoordinatorError
):
    """An actionable decision has no persisted data lineage."""


class MissingModelVersionError(
    DecisionExecutionCoordinatorError
):
    """An actionable decision has no model version."""


class InvalidApprovedDecisionError(
    DecisionExecutionCoordinatorError
):
    """An approved decision has invalid order details."""


@dataclass(frozen=True)
class CoordinatedDecision:
    decision: TradeDecision
    prepared_order: PreparedOrder | None
    validated_timestamp: ValidatedDecisionTimestamp | None

    @property
    def order_created(self) -> bool:
        return self.prepared_order is not None


class DecisionExecutionCoordinator:
    """
    Convert approved decisions into persisted PENDING orders.

    A real ExecutionService must provide a scheduler.
    Calendar agreement is checked before persistence.

    Older test fakes without a scheduler retain their
    existing behavior; the post-preparation check still
    verifies the plan they return.
    """

    ACTIONABLE_STATUSES = frozenset(
        {
            DecisionStatus.BUY_APPROVED,
            DecisionStatus.EXIT_APPROVED,
        }
    )

    def __init__(
        self,
        execution_service: ExecutionService,
        timestamp_validator: DecisionTimestampValidator | None = None,
    ) -> None:
        self.execution_service = execution_service
        self.timestamp_validator = (
            timestamp_validator
            if timestamp_validator is not None
            else DecisionTimestampValidator()
        )

    def coordinate(
        self,
        decision: TradeDecision,
        decision_timestamp: datetime,
        decision_run_id: str | None,
        model_version: str | None,
        order_id: str | None = None,
    ) -> CoordinatedDecision:

        if decision.status not in self.ACTIONABLE_STATUSES:
            return CoordinatedDecision(
                decision=decision,
                prepared_order=None,
                validated_timestamp=None,
            )

        source_session = decision.signal.source_session

        if source_session is None:
            raise MissingDecisionSourceSessionError(
                "Approved decision does not contain "
                "a completed source session."
            )

        decision_run_id = (
            decision_run_id.strip()
            if decision_run_id is not None
            else ""
        )

        if not decision_run_id:
            raise MissingDecisionRunIdError(
                "Approved decisions require an explicit "
                "decision_run_id."
            )

        model_version = (
            model_version.strip()
            if model_version is not None
            else ""
        )

        if not model_version:
            raise MissingModelVersionError(
                "Approved decisions require an explicit "
                "model_version."
            )

        if decision.side is None:
            raise InvalidApprovedDecisionError(
                "Approved decision has no order side."
            )

        if decision.quantity is None or decision.quantity <= 0:
            raise InvalidApprovedDecisionError(
                "Approved decision must have a positive quantity."
            )

        if (
            decision.status == DecisionStatus.BUY_APPROVED
            and decision.side != OrderSide.BUY
        ):
            raise InvalidApprovedDecisionError(
                "BUY_APPROVED decision must use OrderSide.BUY."
            )

        if (
            decision.status == DecisionStatus.EXIT_APPROVED
            and decision.side != OrderSide.SELL
        ):
            raise InvalidApprovedDecisionError(
                "EXIT_APPROVED decision must use OrderSide.SELL."
            )

        validated_timestamp = self.timestamp_validator.validate(
            source_session=source_session,
            decision_timestamp=decision_timestamp,
        )

        # Real services must expose the scheduler used by
        # prepare_order(). Legacy test fakes may omit it.
        scheduler = getattr(
            self.execution_service,
            "scheduler",
            None,
        )

        if scheduler is None:
            if isinstance(
                self.execution_service,
                ExecutionService,
            ):
                raise DecisionExecutionCoordinatorError(
                    "ExecutionService has no scheduler. "
                    "No order was prepared."
                )
        else:
            # Calendar agreement BEFORE order persistence.
            expected_plan = scheduler.create_plan(
                validated_timestamp.decision_timestamp_utc
            )

            if (
                expected_plan.execution_session
                != validated_timestamp.next_execution_session
            ):
                raise DecisionExecutionCoordinatorError(
                    "Decision timestamp validator and execution "
                    "scheduler disagree on the next execution "
                    "session. No order was prepared."
                )

        prepared = self.execution_service.prepare_order(
            ticker=decision.signal.ticker,
            side=decision.side,
            quantity=decision.quantity,
            signal_timestamp=(
                validated_timestamp.decision_timestamp_utc
            ),
            decision_run_id=decision_run_id,
            model_version=model_version,
            order_id=order_id,
        )

        # Defensive consistency check. If this fails, an
        # order may already have been persisted; inspect
        # it before retrying.
        if (
            prepared.execution_plan.execution_session
            != validated_timestamp.next_execution_session
        ):
            raise DecisionExecutionCoordinatorError(
                "Prepared order's execution session differs "
                "from the validated execution session. "
                "Inspect the persisted order before retrying."
            )

        return CoordinatedDecision(
            decision=decision,
            prepared_order=prepared,
            validated_timestamp=validated_timestamp,
        )