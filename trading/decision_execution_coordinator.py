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
    """
    Raised when an actionable decision does not identify
    the completed market session that produced it.
    """


class MissingDecisionRunIdError(
    DecisionExecutionCoordinatorError
):
    """
    Raised when an actionable decision has no explicit
    persisted decision-data lineage.
    """


class MissingModelVersionError(
    DecisionExecutionCoordinatorError
):
    """
    Raised when an actionable decision has no model version.
    """


class InvalidApprovedDecisionError(
    DecisionExecutionCoordinatorError
):
    """
    Raised when a decision claims to be approved but is
    missing the side or quantity required to create an order.
    """


@dataclass(frozen=True)
class CoordinatedDecision:
    """
    Result of attempting to convert a TradeDecision
    into a persisted PENDING order.

    prepared_order is None for decisions that should
    not create an order.
    """

    decision: TradeDecision

    prepared_order: PreparedOrder | None

    validated_timestamp: (
        ValidatedDecisionTimestamp | None
    )

    @property
    def order_created(
        self,
    ) -> bool:

        return (
            self.prepared_order
            is not None
        )


class DecisionExecutionCoordinator:
    """
    Safe bridge between DecisionPipeline and
    ExecutionService.

    Responsibilities:

    1. Never create orders for non-approved decisions.

    2. Require explicit decision-data lineage.

    3. Require a model version.

    4. Validate the decision timestamp against the
       signal's completed source session.

    5. Verify the timestamp validator and execution
       scheduler agree on the next execution session.

    6. Persist the approved order through
       ExecutionService.prepare_order().

    The coordinator does NOT:
        - calculate signals
        - size positions
        - perform risk calculations
        - execute fills
        - fetch market data

    Those responsibilities remain in their existing
    modules.
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
        timestamp_validator: (
            DecisionTimestampValidator | None
        ) = None,
    ) -> None:

        self.execution_service = (
            execution_service
        )

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
        """
        Convert one already-generated TradeDecision
        into a persisted order when appropriate.

        Non-actionable outcomes return without creating
        or persisting an order.
        """

        # -------------------------------------------------
        # NON-ACTIONABLE DECISIONS
        # -------------------------------------------------

        if (
            decision.status
            not in self.ACTIONABLE_STATUSES
        ):
            return CoordinatedDecision(
                decision=decision,
                prepared_order=None,
                validated_timestamp=None,
            )

        # -------------------------------------------------
        # ACTIONABLE DECISION VALIDATION
        # -------------------------------------------------

        source_session = (
            decision.signal.source_session
        )

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

        if (
            decision.quantity is None
            or decision.quantity <= 0
        ):
            raise InvalidApprovedDecisionError(
                "Approved decision must have a "
                "positive quantity."
            )

        # -------------------------------------------------
        # STATUS / SIDE CONSISTENCY
        # -------------------------------------------------

        if (
            decision.status
            == DecisionStatus.BUY_APPROVED
            and decision.side != OrderSide.BUY
        ):
            raise InvalidApprovedDecisionError(
                "BUY_APPROVED decision must use "
                "OrderSide.BUY."
            )

        if (
            decision.status
            == DecisionStatus.EXIT_APPROVED
            and decision.side != OrderSide.SELL
        ):
            raise InvalidApprovedDecisionError(
                "EXIT_APPROVED decision must use "
                "OrderSide.SELL."
            )

        # -------------------------------------------------
        # ANTI-LOOKAHEAD TIMESTAMP VALIDATION
        # -------------------------------------------------

        validated_timestamp = (
            self.timestamp_validator.validate(
                source_session=source_session,
                decision_timestamp=(
                    decision_timestamp
                ),
            )
        )

        # -------------------------------------------------
        # ORDER PREPARATION
        # -------------------------------------------------

        prepared = (
            self.execution_service.prepare_order(
                ticker=(
                    decision.signal.ticker
                ),
                side=decision.side,
                quantity=decision.quantity,
                signal_timestamp=(
                    validated_timestamp
                    .decision_timestamp_utc
                ),
                decision_run_id=(
                    decision_run_id
                ),
                model_version=(
                    model_version
                ),
                order_id=order_id,
            )
        )

        # -------------------------------------------------
        # CROSS-CHECK CALENDAR AGREEMENT
        # -------------------------------------------------

        if (
            prepared.execution_plan
            .execution_session
            != validated_timestamp
            .next_execution_session
        ):
            raise DecisionExecutionCoordinatorError(
                "Decision timestamp validator and "
                "execution scheduler disagree on "
                "the next execution session."
            )

        return CoordinatedDecision(
            decision=decision,
            prepared_order=prepared,
            validated_timestamp=(
                validated_timestamp
            ),
        )