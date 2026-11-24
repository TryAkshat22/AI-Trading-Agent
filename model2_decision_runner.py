from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Mapping

from database.storage import MarketDataStorage

from model2_config import (
    MODEL_2_ACCOUNT_ID,
    MODEL_2_VERSION,
)

from model2_decision_context import (
    Model2DecisionContext,
    build_model2_decision_context,
)

from model2_trade_selector import (
    Model2TradeSelection,
    select_model2_trades,
)

from model2_universe import MODEL2_TICKERS

from risk.risk_engine import RiskEngine

from services.data_quality import (
    DataQualityReport,
    MarketDataQualityValidator,
)

from services.market_data import (
    MarketDataResult,
    YahooFinanceProvider,
)

from trading.daily_batch_runner import (
    DailyBatchResult,
    DailyBatchRunnerError,
    TickerBatchResult,
)

from trading.daily_decision_orchestrator import (
    DailyDecisionOrchestrator,
    DailyDecisionResult,
)

from trading.daily_decision_runner import (
    DailyDecisionRunResult,
    DailyDecisionRunnerError,
)

from trading.decision_execution_coordinator import (
    CoordinatedDecision,
    DecisionExecutionCoordinator,
)

from trading.execution_service import ExecutionService


MODEL_2_TICKERS = MODEL2_TICKERS

MODEL_2_MAX_NEW_BUYS = 5
MODEL_2_MAX_BUYS_PER_GROUP = 2


@dataclass(frozen=True)
class _EvaluatedTicker:
    ticker: str
    decision_run_id: str
    decision: object


class Model2RankedBatchRunner:
    """
    Model 2 two-phase decision batch.

    Phase 1:
        Evaluate every ticker without creating orders.

    Phase 2:
        Select every approved EXIT plus the strongest
        approved BUYs.

    BUY limits:
        maximum 5 total
        maximum 2 per Model 2 group

    Model 1 code is not modified.
    """

    def __init__(
        self,
        *,
        tickers,
        market_data_fetcher,
        quality_report_builder,
        decision_orchestrator,
        max_new_buys: int = MODEL_2_MAX_NEW_BUYS,
        max_buys_per_group: int = (
            MODEL_2_MAX_BUYS_PER_GROUP
        ),
    ) -> None:

        normalized = []
        seen = set()

        for raw_ticker in tickers:

            ticker = (
                str(raw_ticker)
                .strip()
                .upper()
            )

            if not ticker:
                raise DailyBatchRunnerError(
                    "Ticker universe contains "
                    "an empty ticker."
                )

            if ticker in seen:
                continue

            seen.add(ticker)
            normalized.append(ticker)

        if not normalized:
            raise DailyBatchRunnerError(
                "Ticker universe cannot be empty."
            )

        self.tickers = tuple(normalized)

        self.market_data_fetcher = (
            market_data_fetcher
        )

        self.quality_report_builder = (
            quality_report_builder
        )

        self.decision_orchestrator = (
            decision_orchestrator
        )

        self.max_new_buys = (
            max_new_buys
        )

        self.max_buys_per_group = (
            max_buys_per_group
        )

        self.last_selection: (
            Model2TradeSelection | None
        ) = None

    def run(
        self,
        decision_timestamp: datetime,
        market_prices: (
            Mapping[str, object] | None
        ) = None,
        order_id_factory: (
            Callable[[str], str | None]
            | None
        ) = None,
    ) -> DailyBatchResult:

        shared_prices = dict(
            market_prices
            if market_prices is not None
            else {}
        )

        evaluated = {}
        evaluation_failures = {}

        # ====================================================
        # PHASE 1
        #
        # Evaluate all tickers.
        # Do NOT create orders yet.
        # ====================================================

        for ticker in self.tickers:

            try:

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
                    raise DailyBatchRunnerError(
                        "Market-data provider returned "
                        "the wrong ticker. "
                        f"Requested: {ticker}. "
                        f"Received: {actual_ticker}."
                    )

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
                    raise DailyBatchRunnerError(
                        "Quality report ticker does not "
                        "match requested ticker. "
                        f"Requested: {ticker}. "
                        f"Received: {quality_ticker}."
                    )

                persisted_snapshot = (
                    self.decision_orchestrator
                    .market_storage
                    .save_market_snapshot(
                        result=market_result,
                        quality_report=(
                            quality_report
                        ),
                    )
                )

                decision = (
                    self.decision_orchestrator
                    .decision_pipeline
                    .evaluate(
                        market_result=(
                            market_result
                        ),
                        quality_report=(
                            quality_report
                        ),
                        market_prices=(
                            shared_prices
                        ),
                    )
                )

                evaluated[ticker] = (
                    _EvaluatedTicker(
                        ticker=ticker,
                        decision_run_id=(
                            persisted_snapshot.run_id
                        ),
                        decision=decision,
                    )
                )

            except Exception as exc:

                evaluation_failures[
                    ticker
                ] = exc

        # ====================================================
        # PHASE 2
        #
        # Rank successfully evaluated decisions.
        #
        # Existing partial-failure behavior is preserved:
        # failures are reported, but successful decisions
        # may still create orders before the overall batch
        # is marked failed by the command layer.
        # ====================================================

        selection = select_model2_trades(
            [
                evaluated[ticker].decision
                for ticker in self.tickers
                if ticker in evaluated
            ],
            max_new_buys=(
                self.max_new_buys
            ),
            max_buys_per_group=(
                self.max_buys_per_group
            ),
        )

        self.last_selection = selection

        selected = set(
            selection.selected_tickers
        )

        results = []

        for ticker in self.tickers:

            failure = (
                evaluation_failures
                .get(ticker)
            )

            if failure is not None:

                results.append(
                    TickerBatchResult(
                        ticker=ticker,
                        success=False,
                        decision_result=None,
                        error_type=(
                            type(
                                failure
                            ).__name__
                        ),
                        error_message=str(
                            failure
                        ),
                    )
                )

                continue

            item = evaluated[ticker]
            decision = item.decision

            # ------------------------------------------------
            # Not selected:
            #
            # Keep the completed decision result, but do not
            # persist a PENDING order.
            # ------------------------------------------------

            if ticker not in selected:

                result = DailyDecisionResult(
                    decision_run_id=(
                        item.decision_run_id
                    ),
                    decision=decision,
                    coordinated=(
                        CoordinatedDecision(
                            decision=decision,
                            prepared_order=None,
                            validated_timestamp=None,
                        )
                    ),
                )

                results.append(
                    TickerBatchResult(
                        ticker=ticker,
                        success=True,
                        decision_result=result,
                        error_type=None,
                        error_message=None,
                    )
                )

                continue

            # ------------------------------------------------
            # Selected:
            #
            # Use the existing coordinator and execution
            # service to create the PENDING order.
            # ------------------------------------------------

            order_id = None

            if order_id_factory is not None:

                order_id = (
                    order_id_factory(
                        ticker
                    )
                )

            try:

                coordinated = (
                    self.decision_orchestrator
                    .coordinator
                    .coordinate(
                        decision=decision,
                        decision_timestamp=(
                            decision_timestamp
                        ),
                        decision_run_id=(
                            item.decision_run_id
                        ),
                        model_version=(
                            self.decision_orchestrator
                            .model_version
                        ),
                        order_id=order_id,
                    )
                )

                result = DailyDecisionResult(
                    decision_run_id=(
                        item.decision_run_id
                    ),
                    decision=decision,
                    coordinated=coordinated,
                )

                results.append(
                    TickerBatchResult(
                        ticker=ticker,
                        success=True,
                        decision_result=result,
                        error_type=None,
                        error_message=None,
                    )
                )

            except Exception as exc:

                results.append(
                    TickerBatchResult(
                        ticker=ticker,
                        success=False,
                        decision_result=None,
                        error_type=(
                            type(exc).__name__
                        ),
                        error_message=str(
                            exc
                        ),
                    )
                )

        return DailyBatchResult(
            started_at_utc=(
                decision_timestamp
            ),
            results=tuple(
                results
            ),
        )


class Model2RankedDecisionRunner:
    """
    Top-level Model 2 decision runner with ranking.
    """

    def __init__(
        self,
        batch_runner: Model2RankedBatchRunner,
    ) -> None:

        self.batch_runner = (
            batch_runner
        )

    def run(
        self,
        decision_timestamp: datetime,
        market_prices: (
            Mapping[str, object] | None
        ) = None,
        order_id_factory: (
            Callable[[str], str | None]
            | None
        ) = None,
    ) -> DailyDecisionRunResult:

        if not isinstance(
            decision_timestamp,
            datetime,
        ):
            raise TypeError(
                "decision_timestamp must be "
                "a datetime.datetime."
            )

        if decision_timestamp.tzinfo is None:
            raise DailyDecisionRunnerError(
                "decision_timestamp must be "
                "timezone-aware."
            )

        batch_result = (
            self.batch_runner.run(
                decision_timestamp=(
                    decision_timestamp
                ),
                market_prices=(
                    market_prices
                ),
                order_id_factory=(
                    order_id_factory
                ),
            )
        )

        return DailyDecisionRunResult(
            decision_timestamp_utc=(
                decision_timestamp
            ),
            batch_result=batch_result,
        )


@dataclass(frozen=True)
class Model2DecisionComponents:
    context: Model2DecisionContext
    market_storage: MarketDataStorage
    execution_service: ExecutionService
    coordinator: DecisionExecutionCoordinator
    orchestrator: DailyDecisionOrchestrator
    batch_runner: Model2RankedBatchRunner
    decision_runner: Model2RankedDecisionRunner


def build_model2_decision_components(
) -> Model2DecisionComponents:

    context = build_model2_decision_context()

    if context.account_id != MODEL_2_ACCOUNT_ID:
        raise RuntimeError(
            "Unexpected Model 2 account."
        )

    if context.model_version != MODEL_2_VERSION:
        raise RuntimeError(
            "Unexpected Model 2 version."
        )

    if (
        context.database_path
        == context.observation_database_path
    ):
        raise RuntimeError(
            "Model 2 trading and Model 1 observation "
            "databases must differ."
        )

    market_storage = MarketDataStorage(
        context.database_path
    )

    execution_service = ExecutionService(
        account_storage=(
            context.account_storage
        ),
        trading_storage=(
            context.trading_storage
        ),
        risk_engine=RiskEngine(),
        account_id=(
            MODEL_2_ACCOUNT_ID
        ),
    )

    coordinator = (
        DecisionExecutionCoordinator(
            execution_service=(
                execution_service
            )
        )
    )

    orchestrator = DailyDecisionOrchestrator(
        market_storage=market_storage,
        decision_pipeline=(
            context.decision_pipeline
        ),
        coordinator=coordinator,
        model_version=MODEL_2_VERSION,
    )

    provider = YahooFinanceProvider()

    validator = MarketDataQualityValidator(
        calendar_name="NYSE"
    )

    def fetch_market_data(
        ticker: str,
    ) -> MarketDataResult:

        return provider.get_daily_history(
            ticker=ticker,
            period="1y",
        )

    def build_quality_report(
        market_result: MarketDataResult,
    ) -> DataQualityReport:

        return validator.validate(
            market_result
        )

    batch_runner = (
        Model2RankedBatchRunner(
            tickers=MODEL2_TICKERS,
            market_data_fetcher=(
                fetch_market_data
            ),
            quality_report_builder=(
                build_quality_report
            ),
            decision_orchestrator=(
                orchestrator
            ),
            max_new_buys=(
                MODEL_2_MAX_NEW_BUYS
            ),
            max_buys_per_group=(
                MODEL_2_MAX_BUYS_PER_GROUP
            ),
        )
    )

    decision_runner = (
        Model2RankedDecisionRunner(
            batch_runner=batch_runner
        )
    )

    return Model2DecisionComponents(
        context=context,
        market_storage=market_storage,
        execution_service=(
            execution_service
        ),
        coordinator=coordinator,
        orchestrator=orchestrator,
        batch_runner=batch_runner,
        decision_runner=decision_runner,
    )