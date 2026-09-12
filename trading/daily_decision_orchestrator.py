from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from database.storage import (
    MarketDataStorage,
)
from services.data_quality import (
    DataQualityReport,
)
from services.market_data import (
    MarketDataResult,
)
from trading.decision_execution_coordinator import (
    CoordinatedDecision,
    DecisionExecutionCoordinator,
)
from trading.decision_pipeline import (
    TradeDecision,
)


class DailyDecisionOrchestratorError(Exception):
    """
    Base exception for daily decision-cycle failures.
    """


class MissingModelVersionError(
    DailyDecisionOrchestratorError
):
    """
    Raised when the orchestrator has no explicit
    model version.
    """


class InvalidDecisionArgumentsError(
    DailyDecisionOrchestratorError
):
    """
    Raised when decision_kwargs attempts to override
    orchestrator-controlled inputs.
    """


@dataclass(frozen=True)
class DailyDecisionResult:
    """
    Complete result of one Model 1 decision cycle.

    decision_run_id:
        persisted market-data run used for the decision

    decision:
        result produced by DecisionPipeline

    coordinated:
        result of attempting to convert the decision
        into a persistent PENDING order
    """

    decision_run_id: str

    decision: TradeDecision

    coordinated: CoordinatedDecision

    @property
    def order_created(
        self,
    ) -> bool:
        return (
            self.coordinated.order_created
        )

    @property
    def prepared_order(
        self,
    ):
        return (
            self.coordinated.prepared_order
        )


class DailyDecisionOrchestrator:
    """
    Runs one controlled daily Model 1 decision cycle.

    Flow:

        validated market data
                ↓
        persist market snapshot
                ↓
        decision_run_id
                ↓
        DecisionPipeline.evaluate()
                ↓
        TradeDecision
                ↓
        DecisionExecutionCoordinator
                ↓
        timestamp + lineage validation
                ↓
        optional PENDING order

    Responsibilities intentionally excluded:

        - downloading market data
        - executing next-session fills
        - scheduling background jobs
        - changing model parameters
        - running multiple tickers concurrently

    Those remain separate concerns.
    """

    _RESERVED_DECISION_ARGUMENTS = frozenset(
        {
            "market_result",
            "quality_report",
        }
    )

    def __init__(
        self,
        market_storage: MarketDataStorage,
        decision_pipeline,
        coordinator: DecisionExecutionCoordinator,
        model_version: str,
    ) -> None:

        model_version = (
            model_version.strip()
        )

        if not model_version:
            raise MissingModelVersionError(
                "model_version cannot be empty."
            )

        self.market_storage = (
            market_storage
        )

        self.decision_pipeline = (
            decision_pipeline
        )

        self.coordinator = (
            coordinator
        )

        self.model_version = (
            model_version
        )

    def run(
        self,
        market_result: MarketDataResult,
        quality_report: DataQualityReport,
        decision_timestamp: datetime,
        decision_kwargs: (
            dict[str, Any] | None
        ) = None,
        order_id: str | None = None,
    ) -> DailyDecisionResult:
        """
        Run one complete decision cycle.

        decision_kwargs contains any additional inputs
        required by DecisionPipeline.evaluate(), such as
        valuation/market-price information.

        The orchestrator owns market_result and
        quality_report, so callers cannot override them.
        """

        extra_arguments = dict(
            decision_kwargs
            if decision_kwargs is not None
            else {}
        )

        self._validate_decision_arguments(
            extra_arguments
        )

        # -------------------------------------------------
        # 1. PERSIST THE EXACT DECISION DATA
        # -------------------------------------------------

        persisted_snapshot = (
            self.market_storage
            .save_market_snapshot(
                result=market_result,
                quality_report=(
                    quality_report
                ),
            )
        )

        decision_run_id = (
            persisted_snapshot.run_id
        )

        # -------------------------------------------------
        # 2. GENERATE THE DECISION
        # -------------------------------------------------

        decision = (
            self.decision_pipeline.evaluate(
                market_result=(
                    market_result
                ),
                quality_report=(
                    quality_report
                ),
                **extra_arguments,
            )
        )

        # -------------------------------------------------
        # 3. COORDINATE DECISION -> ORDER
        # -------------------------------------------------

        coordinated = (
            self.coordinator.coordinate(
                decision=decision,
                decision_timestamp=(
                    decision_timestamp
                ),
                decision_run_id=(
                    decision_run_id
                ),
                model_version=(
                    self.model_version
                ),
                order_id=order_id,
            )
        )

        return DailyDecisionResult(
            decision_run_id=(
                decision_run_id
            ),
            decision=decision,
            coordinated=coordinated,
        )

    def _validate_decision_arguments(
        self,
        arguments: dict[str, Any],
    ) -> None:
        """
        Prevent callers from replacing data controlled
        by the orchestrator.

        Without this check a caller could accidentally
        evaluate one MarketDataResult while persisting
        another, breaking lineage.
        """

        conflicting = (
            self._RESERVED_DECISION_ARGUMENTS
            & arguments.keys()
        )

        if conflicting:
            raise InvalidDecisionArgumentsError(
                "decision_kwargs cannot override "
                "orchestrator-controlled arguments: "
                f"{sorted(conflicting)}."
            )