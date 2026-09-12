from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Mapping

from database.execution_attempt_storage import (
    ExecutionAttemptOutcome,
    ExecutionAttemptRecord,
    ExecutionAttemptStorage,
)
from database.storage import (
    MarketDataStorage,
)
from services.data_quality import (
    DataQualityReport,
)
from services.market_data import (
    MarketDataResult,
)
from trading.execution_observation import (
    ExecutionObservationValidator,
    ValidatedExecutionObservation,
)
from trading.execution_service import (
    ExecutedOrder,
    ExecutionService,
)
from trading.orders import (
    OrderStatus,
)


class ExecutionOrchestratorError(Exception):
    """
    Base exception for execution orchestration failures.
    """


class StoredOrderMissingError(
    ExecutionOrchestratorError
):
    """
    Raised when the requested order cannot be found.
    """


class ExecutionSessionMismatchError(
    ExecutionOrchestratorError
):
    """
    Raised when the validated execution session differs
    from the persisted order's execution session.
    """


@dataclass(frozen=True)
class ExecutionOrchestratorResult:
    """
    Result of one successfully completed execution.
    """

    execution_run_id: str

    execution_attempt: ExecutionAttemptRecord

    validated_observation: (
        ValidatedExecutionObservation
    )

    executed_order: ExecutedOrder

    @property
    def fill(
        self,
    ):
        return (
            self.executed_order.fill
        )

    @property
    def portfolio_snapshot_id(
        self,
    ):
        return (
            self.executed_order
            .portfolio_snapshot_id
        )


class ExecutionOrchestrator:
    """
    Auditable execution coordinator for Model 1.

    Flow:

        PENDING order
            ↓
        validate execution observation
            ↓
        persist execution snapshot
            ↓
        execution_run_id
            ↓
        STARTED execution attempt
            ↓
        ExecutionService.execute_order()
            ↓
        ┌───────────┬────────────┐
        ▼           ▼            ▼
      FILLED     REJECTED      FAILED

    The execution attempt is persisted BEFORE the
    execution service runs.

    Therefore every accepted execution observation
    remains linked to its eventual outcome.
    """

    def __init__(
        self,
        market_storage: MarketDataStorage,
        trading_storage,
        execution_service: ExecutionService,
        execution_attempt_storage: (
            ExecutionAttemptStorage
        ),
        observation_validator: (
            ExecutionObservationValidator | None
        ) = None,
    ) -> None:

        self.market_storage = (
            market_storage
        )

        self.trading_storage = (
            trading_storage
        )

        self.execution_service = (
            execution_service
        )

        self.execution_attempt_storage = (
            execution_attempt_storage
        )

        self.observation_validator = (
            observation_validator
            if observation_validator is not None
            else ExecutionObservationValidator()
        )

    def execute(
        self,
        order_id: str,
        market_result: MarketDataResult,
        quality_report: DataQualityReport,
        execution_observed_at: datetime,
        execution_market_prices: (
            Mapping[
                str,
                Decimal | int | float,
            ]
            | None
        ) = None,
        valuation_prices: (
            Mapping[
                str,
                Decimal | int | float,
            ]
            | None
        ) = None,
        recorded_at_utc: (
            datetime | None
        ) = None,
    ) -> ExecutionOrchestratorResult:
        """
        Run one auditable execution attempt.
        """

        stored_order = (
            self.trading_storage
            .get_order(
                order_id
            )
        )

        if stored_order is None:
            raise StoredOrderMissingError(
                "Stored order does not exist: "
                f"{order_id}."
            )

        execution_session = (
            stored_order.execution_session
        )

        # -------------------------------------------------
        # 1. TIME-AUTHENTIC EXECUTION OBSERVATION
        # -------------------------------------------------

        validated_observation = (
            self.observation_validator
            .validate(
                market_result=(
                    market_result
                ),
                execution_session=(
                    execution_session
                ),
                execution_observed_at=(
                    execution_observed_at
                ),
                expected_ticker=(
                    stored_order.ticker
                ),
            )
        )

        if (
            validated_observation
            .execution_session
            != execution_session
        ):
            raise (
                ExecutionSessionMismatchError(
                    "Validated execution session "
                    "does not match the persisted "
                    "order execution session."
                )
            )

        # -------------------------------------------------
        # 2. PERSIST EXECUTION OBSERVATION
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

        execution_run_id = (
            persisted_snapshot.run_id
        )

        # -------------------------------------------------
        # 3. CREATE AUDIT RECORD BEFORE EXECUTION
        # -------------------------------------------------

        attempt = (
            self.execution_attempt_storage
            .start_attempt(
                order_id=order_id,
                execution_run_id=(
                    execution_run_id
                ),
                execution_observed_at_utc=(
                    validated_observation
                    .execution_observed_at_utc
                ),
            )
        )

        # -------------------------------------------------
        # 4. EXECUTION
        # -------------------------------------------------

        try:

            executed_order = (
                self.execution_service
                .execute_order(
                    order_id=order_id,
                    market_result=(
                        market_result
                    ),
                    quality_report=(
                        quality_report
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
                    execution_run_id=(
                        execution_run_id
                    ),
                )
            )

        except Exception as exc:

            self._finalize_failed_execution(
                attempt_id=(
                    attempt.attempt_id
                ),
                order_id=order_id,
                exception=exc,
            )

            raise

        # -------------------------------------------------
        # 5. SUCCESSFUL EXECUTION
        # -------------------------------------------------

        finalized_attempt = (
            self.execution_attempt_storage
            .finalize_attempt(
                attempt_id=(
                    attempt.attempt_id
                ),
                outcome=(
                    ExecutionAttemptOutcome.FILLED
                ),
            )
        )

        return ExecutionOrchestratorResult(
            execution_run_id=(
                execution_run_id
            ),
            execution_attempt=(
                finalized_attempt
            ),
            validated_observation=(
                validated_observation
            ),
            executed_order=(
                executed_order
            ),
        )

    def _finalize_failed_execution(
        self,
        attempt_id: str,
        order_id: str,
        exception: Exception,
    ) -> None:
        """
        Determine what actually happened from persistent
        order state.

        This matters because exception != rejection.

        REJECTED:
            business/risk decision

        FAILED:
            operational/software failure while order
            remains unexecuted

        FILLED:
            trade persisted before a later operational
            exception occurred
        """

        persisted_status = (
            self.trading_storage
            .get_order_status(
                order_id
            )
        )

        error_type = (
            type(
                exception
            ).__name__
        )

        error_message = str(
            exception
        )

        if (
            persisted_status
            == OrderStatus.REJECTED.value
        ):

            outcome = (
                ExecutionAttemptOutcome.REJECTED
            )

        elif (
            persisted_status
            == OrderStatus.FILLED.value
        ):

            # Trade happened. Do not falsely call the
            # attempt a failed trade simply because
            # something downstream raised an error.
            outcome = (
                ExecutionAttemptOutcome.FILLED
            )

        else:

            outcome = (
                ExecutionAttemptOutcome.FAILED
            )

        self.execution_attempt_storage.finalize_attempt(
            attempt_id=attempt_id,
            outcome=outcome,
            error_type=error_type,
            error_message=error_message,
        )