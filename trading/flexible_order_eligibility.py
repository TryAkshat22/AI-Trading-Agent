
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from audit_pending_orders import PendingOrderAuditor
from database.pending_order_query import PendingOrderQuery
from database.storage import get_default_database_path
from trading.flexible_observation_selector import (
    FlexibleObservationSelector,
)


class FlexibleOrderEligibilityError(Exception):
    """The requested eligibility check cannot be trusted."""


@dataclass(frozen=True)
class EligibleFlexibleOrder:
    order_id: str
    ticker: str
    execution_session: date
    model_version: str
    reference_price: float
    price_field: str
    observation_retrieved_at_utc: datetime
    observation_bar_start_utc: datetime


@dataclass(frozen=True)
class IneligibleFlexibleOrder:
    order_id: str
    ticker: str
    reason: str


@dataclass(frozen=True)
class FlexibleEligibilityResult:
    execution_session: date
    checked_at_utc: datetime
    eligible_orders: tuple[EligibleFlexibleOrder, ...]
    ineligible_orders: tuple[IneligibleFlexibleOrder, ...]

    @property
    def eligible_count(self) -> int:
        return len(self.eligible_orders)

    @property
    def ineligible_count(self) -> int:
        return len(self.ineligible_orders)


class FlexibleOrderEligibilityChecker:
    """
    Read-only order and observation eligibility check.

    Requires explicit Model 2 lineage.

    It does not:
      - create orders or execution attempts
      - create fills
      - reject orders
      - change portfolio balances
      - roll orders into another session
    """

    def __init__(
        self,
        database_path: str | Path | None = None,
        pending_order_query: PendingOrderQuery | None = None,
        auditor: PendingOrderAuditor | None = None,
        observation_selector: FlexibleObservationSelector | None = None,
        expected_model_version: str = "model-2-flexible",
    ) -> None:
        if not expected_model_version.strip():
            raise ValueError(
                "expected_model_version cannot be blank."
            )

        if database_path is None:
            database_path = get_default_database_path()

        self.database_path = Path(database_path)
        self.expected_model_version = expected_model_version.strip()

        self.pending_order_query = (
            pending_order_query
            if pending_order_query is not None
            else PendingOrderQuery(self.database_path)
        )

        self.auditor = (
            auditor
            if auditor is not None
            else PendingOrderAuditor(self.database_path)
        )

        self.observation_selector = (
            observation_selector
            if observation_selector is not None
            else FlexibleObservationSelector(
                database_path=self.database_path
            )
        )

    def check(
        self,
        execution_session: date,
        checked_at: datetime,
    ) -> FlexibleEligibilityResult:
        if (
            not isinstance(execution_session, date)
            or isinstance(execution_session, datetime)
        ):
            raise TypeError(
                "execution_session must be a datetime.date."
            )

        if (
            not isinstance(checked_at, datetime)
            or checked_at.tzinfo is None
        ):
            raise FlexibleOrderEligibilityError(
                "checked_at must be a timezone-aware datetime."
            )

        checked_utc = checked_at.astimezone(timezone.utc)

        references = (
            self.pending_order_query.find_for_session(
                execution_session
            )
        )

        audit = self.auditor.audit_session(
            execution_session
        )

        reference_ids = [
            reference.order_id
            for reference in references
        ]

        audit_ids = [
            record.order_id
            for record in audit.records
        ]

        # Fail closed if the two independent discovery
        # paths disagree or contain duplicate order IDs.
        if (
            len(reference_ids) != len(set(reference_ids))
            or len(audit_ids) != len(set(audit_ids))
            or set(reference_ids) != set(audit_ids)
            or audit.execution_session != execution_session
        ):
            raise FlexibleOrderEligibilityError(
                "Pending-order discovery and audit disagree. "
                "No orders have been approved."
            )

        audit_by_id = {
            record.order_id: record
            for record in audit.records
        }

        eligible = []
        ineligible = []

        for reference in references:
            record = audit_by_id[reference.order_id]

            if (
                reference.execution_session != execution_session
                or record.execution_session != execution_session
            ):
                raise FlexibleOrderEligibilityError(
                    "An order belongs to the wrong "
                    "execution session."
                )

            if (
                reference.ticker.strip().upper()
                != record.ticker.strip().upper()
            ):
                raise FlexibleOrderEligibilityError(
                    "Pending-order reference and audit "
                    "disagree about the ticker."
                )

            if reference.model_version != record.model_version:
                raise FlexibleOrderEligibilityError(
                    "Pending-order reference and audit "
                    "disagree about the model version."
                )

            ticker = reference.ticker.strip().upper()

            if (
                reference.model_version
                != self.expected_model_version
            ):
                ineligible.append(
                    IneligibleFlexibleOrder(
                        order_id=reference.order_id,
                        ticker=ticker,
                        reason=(
                            "Order belongs to a different model: "
                            f"{reference.model_version!r}."
                        ),
                    )
                )
                continue

            if not record.clean_for_execution:
                ineligible.append(
                    IneligibleFlexibleOrder(
                        order_id=reference.order_id,
                        ticker=ticker,
                        reason=(
                            "Order failed the existing "
                            "pre-execution audit."
                        ),
                    )
                )
                continue

            try:
                observation = (
                    self.observation_selector.select(
                        ticker=ticker,
                        execution_session=execution_session,
                        checked_at=checked_utc,
                    )
                )

            except Exception as exc:
                ineligible.append(
                    IneligibleFlexibleOrder(
                        order_id=reference.order_id,
                        ticker=ticker,
                        reason=(
                            "No eligible price observation: "
                            f"{type(exc).__name__}: {exc}"
                        ),
                    )
                )
                continue

            eligible.append(
                EligibleFlexibleOrder(
                    order_id=reference.order_id,
                    ticker=ticker,
                    execution_session=execution_session,
                    model_version=self.expected_model_version,
                    reference_price=observation.reference_price,
                    price_field=observation.price_field,
                    observation_retrieved_at_utc=(
                        observation.retrieved_at_utc
                    ),
                    observation_bar_start_utc=(
                        observation.bar_start_utc
                    ),
                )
            )

        return FlexibleEligibilityResult(
            execution_session=execution_session,
            checked_at_utc=checked_utc,
            eligible_orders=tuple(eligible),
            ineligible_orders=tuple(ineligible),
        )