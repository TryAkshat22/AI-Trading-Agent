from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import Callable, Mapping, Sequence

from services.data_quality import (
    DataQualityReport,
)
from services.market_data import (
    MarketDataResult,
)
from trading.execution_orchestrator import (
    ExecutionOrchestrator,
    ExecutionOrchestratorResult,
)
from trading.orders import (
    OrderStatus,
)


class PendingExecutionBatchRunnerError(
    Exception
):
    """
    Base exception for execution-batch failures.
    """


class InvalidExecutionBatchError(
    PendingExecutionBatchRunnerError
):
    """
    Raised when the requested execution batch
    itself is invalid.
    """


class ExecutionBatchOutcome(
    str,
    Enum,
):
    """
    Per-order outcome inside one execution batch.

    FILLED:
        trade executed successfully

    REJECTED:
        trading/risk rules deliberately blocked
        execution

    FAILED:
        operational/data/software failure

    SKIPPED:
        order exists but should not be executed
        in this batch
    """

    FILLED = "FILLED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


@dataclass(frozen=True)
class PendingOrderBatchResult:
    """
    Outcome for one order processed by the batch.
    """

    order_id: str

    ticker: str | None

    outcome: ExecutionBatchOutcome

    execution_result: (
        ExecutionOrchestratorResult
        | None
    )

    error_type: str | None

    error_message: str | None

    @property
    def filled(
        self,
    ) -> bool:

        return (
            self.outcome
            == ExecutionBatchOutcome.FILLED
        )

    @property
    def rejected(
        self,
    ) -> bool:

        return (
            self.outcome
            == ExecutionBatchOutcome.REJECTED
        )

    @property
    def failed(
        self,
    ) -> bool:

        return (
            self.outcome
            == ExecutionBatchOutcome.FAILED
        )

    @property
    def skipped(
        self,
    ) -> bool:

        return (
            self.outcome
            == ExecutionBatchOutcome.SKIPPED
        )


@dataclass(frozen=True)
class PendingExecutionBatchResult:
    """
    Aggregate result of one execution batch.
    """

    execution_session: date

    results: tuple[
        PendingOrderBatchResult,
        ...,
    ]

    @property
    def total_orders(
        self,
    ) -> int:

        return len(
            self.results
        )

    @property
    def filled_orders(
        self,
    ) -> int:

        return sum(
            result.filled
            for result in self.results
        )

    @property
    def rejected_orders(
        self,
    ) -> int:

        return sum(
            result.rejected
            for result in self.results
        )

    @property
    def failed_orders(
        self,
    ) -> int:

        return sum(
            result.failed
            for result in self.results
        )

    @property
    def skipped_orders(
        self,
    ) -> int:

        return sum(
            result.skipped
            for result in self.results
        )

    @property
    def problems(
        self,
    ) -> tuple[
        PendingOrderBatchResult,
        ...,
    ]:

        return tuple(
            result
            for result in self.results
            if result.outcome
            in {
                ExecutionBatchOutcome.REJECTED,
                ExecutionBatchOutcome.FAILED,
            }
        )


class PendingExecutionBatchRunner:
    """
    Runs next-open execution across multiple
    persisted paper orders.

    Per order:

        load persisted order
                ↓
        confirm PENDING
                ↓
        confirm target session
                ↓
        fetch execution observation
                ↓
        build execution quality report
                ↓
        determine actual observation time
                ↓
        ExecutionOrchestrator
                ↓
        FILLED / REJECTED / FAILED

    One order failure never terminates the batch.

    The runner deliberately does not duplicate:

        - observation validation
        - execution snapshot persistence
        - execution lineage
        - execution-time risk
        - broker fills
        - rejection persistence
        - portfolio accounting

    Those remain inside the existing execution
    orchestration stack.
    """

    def __init__(
        self,
        trading_storage,

        execution_orchestrator: (
            ExecutionOrchestrator
        ),

        market_data_fetcher: Callable[
            [str],
            MarketDataResult,
        ],

        quality_report_builder: Callable[
            [MarketDataResult],
            DataQualityReport,
        ],

        observation_time_builder: Callable[
            [MarketDataResult],
            datetime,
        ],

    ) -> None:

        self.trading_storage = (
            trading_storage
        )

        self.execution_orchestrator = (
            execution_orchestrator
        )

        self.market_data_fetcher = (
            market_data_fetcher
        )

        self.quality_report_builder = (
            quality_report_builder
        )

        self.observation_time_builder = (
            observation_time_builder
        )

    def run(
        self,
        order_ids: Sequence[str],
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

    ) -> PendingExecutionBatchResult:
        """
        Run one execution batch for exactly one
        intended market session.
        """

        if not isinstance(
            execution_session,
            date,
        ):
            raise TypeError(
                "execution_session must be "
                "a datetime.date."
            )

        normalized_order_ids = (
            self._normalize_order_ids(
                order_ids
            )
        )

        results: list[
            PendingOrderBatchResult
        ] = []

        shared_execution_prices = (
            dict(
                execution_market_prices
                if execution_market_prices
                is not None
                else {}
            )
        )

        shared_valuation_prices = (
            dict(
                valuation_prices
                if valuation_prices
                is not None
                else {}
            )
        )

        for order_id in normalized_order_ids:

            result = (
                self._run_one_order(
                    order_id=order_id,
                    execution_session=(
                        execution_session
                    ),
                    execution_market_prices=(
                        shared_execution_prices
                    ),
                    valuation_prices=(
                        shared_valuation_prices
                    ),
                    recorded_at_utc=(
                        recorded_at_utc
                    ),
                )
            )

            results.append(
                result
            )

        return PendingExecutionBatchResult(
            execution_session=(
                execution_session
            ),
            results=tuple(
                results
            ),
        )

    def _run_one_order(
        self,
        order_id: str,
        execution_session: date,
        execution_market_prices: dict[
            str,
            object,
        ],
        valuation_prices: dict[
            str,
            object,
        ],
        recorded_at_utc: (
            datetime | None
        ),
    ) -> PendingOrderBatchResult:
        """
        Process one order without allowing its
        failure to escape the batch.
        """

        stored_order = None

        try:

            # -----------------------------------------
            # 1. LOAD ORDER
            # -----------------------------------------

            stored_order = (
                self.trading_storage
                .get_order(
                    order_id
                )
            )

            if stored_order is None:

                return (
                    PendingOrderBatchResult(
                        order_id=order_id,
                        ticker=None,
                        outcome=(
                            ExecutionBatchOutcome
                            .FAILED
                        ),
                        execution_result=None,
                        error_type=(
                            "StoredOrderMissing"
                        ),
                        error_message=(
                            "Stored order does not "
                            "exist."
                        ),
                    )
                )

            ticker = (
                str(
                    stored_order.ticker
                )
                .strip()
                .upper()
            )

            # -----------------------------------------
            # 2. ONLY PENDING ORDERS MAY EXECUTE
            # -----------------------------------------

            persisted_status = (
                self.trading_storage
                .get_order_status(
                    order_id
                )
            )

            if (
                persisted_status
                != OrderStatus.PENDING.value
            ):

                return (
                    PendingOrderBatchResult(
                        order_id=order_id,
                        ticker=ticker,
                        outcome=(
                            ExecutionBatchOutcome
                            .SKIPPED
                        ),
                        execution_result=None,
                        error_type=None,
                        error_message=(
                            "Order is not PENDING. "
                            f"Current status: "
                            f"{persisted_status}."
                        ),
                    )
                )

            # -----------------------------------------
            # 3. SESSION GATE
            # -----------------------------------------

            if (
                stored_order.execution_session
                != execution_session
            ):

                return (
                    PendingOrderBatchResult(
                        order_id=order_id,
                        ticker=ticker,
                        outcome=(
                            ExecutionBatchOutcome
                            .SKIPPED
                        ),
                        execution_result=None,
                        error_type=None,
                        error_message=(
                            "Order is scheduled for "
                            f"{stored_order.execution_session}, "
                            "not "
                            f"{execution_session}."
                        ),
                    )
                )

            # -----------------------------------------
            # 4. FETCH EXECUTION OBSERVATION
            # -----------------------------------------

            market_result = (
                self.market_data_fetcher(
                    ticker
                )
            )

            actual_ticker = (
                str(
                    market_result.ticker
                )
                .strip()
                .upper()
            )

            if actual_ticker != ticker:
                raise (
                    PendingExecutionBatchRunnerError(
                        "Execution market-data "
                        "provider returned the "
                        "wrong ticker. "
                        f"Expected: {ticker}. "
                        f"Received: "
                        f"{actual_ticker}."
                    )
                )

            # -----------------------------------------
            # 5. QUALITY REPORT
            # -----------------------------------------

            quality_report = (
                self.quality_report_builder(
                    market_result
                )
            )

            quality_ticker = (
                str(
                    quality_report.ticker
                )
                .strip()
                .upper()
            )

            if quality_ticker != ticker:
                raise (
                    PendingExecutionBatchRunnerError(
                        "Execution quality report "
                        "belongs to the wrong "
                        "ticker. "
                        f"Expected: {ticker}. "
                        f"Received: "
                        f"{quality_ticker}."
                    )
                )

            # -----------------------------------------
            # 6. OBSERVATION TIME
            # -----------------------------------------

            execution_observed_at = (
                self.observation_time_builder(
                    market_result
                )
            )

            # -----------------------------------------
            # 7. AUDITED EXECUTION
            # -----------------------------------------

            execution_result = (
                self.execution_orchestrator
                .execute(
                    order_id=order_id,
                    market_result=(
                        market_result
                    ),
                    quality_report=(
                        quality_report
                    ),
                    execution_observed_at=(
                        execution_observed_at
                    ),
                    execution_market_prices=(
                        execution_market_prices
                        if execution_market_prices
                        else None
                    ),
                    valuation_prices=(
                        valuation_prices
                        if valuation_prices
                        else None
                    ),
                    recorded_at_utc=(
                        recorded_at_utc
                    ),
                )
            )

            return PendingOrderBatchResult(
                order_id=order_id,
                ticker=ticker,
                outcome=(
                    ExecutionBatchOutcome.FILLED
                ),
                execution_result=(
                    execution_result
                ),
                error_type=None,
                error_message=None,
            )

        except Exception as exc:

            ticker = (
                str(
                    stored_order.ticker
                )
                .strip()
                .upper()
                if stored_order is not None
                else None
            )

            outcome = (
                self._classify_failure(
                    order_id
                )
            )

            return PendingOrderBatchResult(
                order_id=order_id,
                ticker=ticker,
                outcome=outcome,
                execution_result=None,
                error_type=(
                    type(
                        exc
                    ).__name__
                ),
                error_message=str(
                    exc
                ),
            )

    def _classify_failure(
        self,
        order_id: str,
    ) -> ExecutionBatchOutcome:
        """
        Classify using persistent truth rather than
        exception type.

        REJECTED persisted state:
            business/risk rejection

        FILLED persisted state:
            trade actually happened even if something
            later raised

        otherwise:
            operational failure
        """

        try:

            persisted_status = (
                self.trading_storage
                .get_order_status(
                    order_id
                )
            )

        except Exception:

            return (
                ExecutionBatchOutcome.FAILED
            )

        if (
            persisted_status
            == OrderStatus.REJECTED.value
        ):
            return (
                ExecutionBatchOutcome.REJECTED
            )

        if (
            persisted_status
            == OrderStatus.FILLED.value
        ):
            return (
                ExecutionBatchOutcome.FILLED
            )

        return ExecutionBatchOutcome.FAILED

    @staticmethod
    def _normalize_order_ids(
        order_ids: Sequence[str],
    ) -> tuple[str, ...]:

        normalized: list[str] = []

        seen: set[str] = set()

        for raw_order_id in order_ids:

            order_id = (
                str(
                    raw_order_id
                )
                .strip()
            )

            if not order_id:

                raise InvalidExecutionBatchError(
                    "Execution batch contains "
                    "an empty order ID."
                )

            if order_id in seen:
                continue

            seen.add(
                order_id
            )

            normalized.append(
                order_id
            )

        if not normalized:

            raise InvalidExecutionBatchError(
                "Execution batch cannot be empty."
            )

        return tuple(
            normalized
        )