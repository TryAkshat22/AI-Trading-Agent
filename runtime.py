from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

from sqlalchemy import text

from app import StatusSummary

from database.account_storage import (
    AccountStorage,
)
from database.equity_storage import (
    EquityStorage,
)
from database.execution_attempt_storage import (
    ExecutionAttemptStorage,
)
from database.pending_order_query import (
    PendingOrderQuery,
)
from database.sqlite_engine import (
    create_sqlite_engine,
)
from database.storage import (
    MarketDataStorage,
    get_default_database_path,
)
from database.trading_storage import (
    TradingStorage,
)

from evaluation.benchmark import (
    BenchmarkComparison,
    BenchmarkService,
)
from evaluation.cash_benchmark import (
    CashBenchmarkService,
)
from evaluation.equal_weight_benchmark import (
    EqualWeightBenchmarkComparison,
    EqualWeightBenchmarkService,
)
from evaluation.equity_tracker import (
    EquityTracker,
    EquityTrackingResult,
)
from evaluation.evaluation_report import (
    EvaluationReport,
    EvaluationReportService,
)
from evaluation.performance_metrics import (
    PerformanceMetrics,
    PerformanceMetricService,
)
from evaluation.portfolio_report import (
    PortfolioReport,
    PortfolioReportService,
)
from evaluation.report_bundle import (
    ReportBundleResult,
    ReportBundleService,
)
from evaluation.report_charts import (
    ReportChartService,
)
from evaluation.report_export import (
    ReportExportService,
)

from risk.position_sizer import (
    PositionSizer,
)
from risk.risk_engine import (
    RiskEngine,
)

from services.data_quality import (
    MarketDataQualityValidator,
)
from services.execution_market_data import (
    YahooNearOpenExecutionProvider,
)
from services.market_data import (
    MarketDataResult,
    YahooFinanceProvider,
)

from signals.signal_engine import (
    SignalEngine,
)

from trading.daily_batch_runner import (
    DailyBatchRunner,
)
from trading.daily_decision_orchestrator import (
    DailyDecisionOrchestrator,
)
from trading.daily_decision_runner import (
    DailyDecisionRunner,
)
from trading.daily_execution_runner import (
    DailyExecutionRunner,
)
from trading.decision_execution_coordinator import (
    DecisionExecutionCoordinator,
)
from trading.decision_pipeline import (
    DecisionPipeline,
)
from trading.execution_observation import (
    ExecutionObservationValidator,
)
from trading.execution_orchestrator import (
    ExecutionOrchestrator,
)
from trading.execution_service import (
    ExecutionService,
)
from trading.pending_execution_batch_runner import (
    PendingExecutionBatchRunner,
)
from trading.portfolio_rebuilder import (
    PortfolioRebuilder,
)


DEFAULT_TICKERS = (
    "AAPL",
    "MSFT",
    "NVDA",
    "AMZN",
    "GOOGL",
    "META",
    "JPM",
    "XOM",
    "JNJ",
    "WMT",
)

DEFAULT_MODEL_VERSION = "model-1"

DEFAULT_STARTING_CASH = Decimal(
    "10000"
)

DEFAULT_BENCHMARK_SYMBOL = "SPY"

NEW_YORK = ZoneInfo(
    "America/New_York"
)


class LiveExecutionDataUnavailableError(
    RuntimeError
):
    pass


def _load_tickers() -> tuple[str, ...]:

    raw = os.getenv(
        "PAPER_TRADING_TICKERS"
    )

    if raw is None:
        return DEFAULT_TICKERS

    tickers = tuple(
        ticker.strip().upper()
        for ticker in raw.split(",")
        if ticker.strip()
    )

    if not tickers:
        raise ValueError(
            "PAPER_TRADING_TICKERS cannot "
            "resolve to an empty universe."
        )

    return tuple(
        dict.fromkeys(
            tickers
        )
    )


def _load_starting_cash() -> Decimal:

    raw = os.getenv(
        "PAPER_TRADING_STARTING_CASH"
    )

    if raw is None:
        return DEFAULT_STARTING_CASH

    value = Decimal(
        raw
    )

    if value <= 0:
        raise ValueError(
            "PAPER_TRADING_STARTING_CASH "
            "must be positive."
        )

    return value


def _load_model_version() -> str:

    value = (
        os.getenv(
            "PAPER_TRADING_MODEL_VERSION",
            DEFAULT_MODEL_VERSION,
        )
        .strip()
    )

    if not value:
        raise ValueError(
            "PAPER_TRADING_MODEL_VERSION "
            "cannot be blank."
        )

    return value


def _load_benchmark_symbol() -> str:

    value = (
        os.getenv(
            "PAPER_TRADING_BENCHMARK",
            DEFAULT_BENCHMARK_SYMBOL,
        )
        .strip()
        .upper()
    )

    if not value:
        raise ValueError(
            "PAPER_TRADING_BENCHMARK "
            "cannot be blank."
        )

    return value


@dataclass(frozen=True)
class RuntimeConfiguration:

    database_path: Path
    tickers: tuple[str, ...]
    model_version: str
    starting_cash: Decimal
    benchmark_symbol: str
    decision_history_period: str = "1y"


class LiveTradingRuntime:

    def __init__(
        self,
        config: RuntimeConfiguration,
        execution_provider_factory: (
            Callable[..., object]
            | None
        ) = None,
    ) -> None:

        self.config = config

        self.execution_provider_factory = (
            execution_provider_factory
            if execution_provider_factory
            is not None
            else YahooNearOpenExecutionProvider
        )

        # =====================================================
        # DATABASE
        # =====================================================

        self.market_storage = (
            MarketDataStorage(
                config.database_path
            )
        )

        self.account_storage = (
            AccountStorage(
                config.database_path
            )
        )

        self.trading_storage = (
            TradingStorage(
                config.database_path
            )
        )

        self.execution_attempt_storage = (
            ExecutionAttemptStorage(
                config.database_path
            )
        )

        self.pending_order_query = (
            PendingOrderQuery(
                config.database_path
            )
        )

        self.equity_storage = (
            EquityStorage(
                config.database_path
            )
        )

        self.market_storage.initialize()
        self.account_storage.initialize()
        self.trading_storage.initialize()
        self.execution_attempt_storage.initialize()
        self.equity_storage.initialize()

        self.account = (
            self.account_storage
            .get_or_create(
                starting_cash=(
                    config.starting_cash
                )
            )
        )

        # =====================================================
        # MARKET DATA
        # =====================================================

        self.market_provider = (
            YahooFinanceProvider()
        )

        self.quality_validator = (
            MarketDataQualityValidator(
                calendar_name="NYSE"
            )
        )

        self._decision_market_cache: dict[
            str,
            MarketDataResult,
        ] = {}

        # =====================================================
        # ENGINES
        # =====================================================

        self.signal_engine = (
            SignalEngine()
        )

        self.position_sizer = (
            PositionSizer()
        )

        self.risk_engine = (
            RiskEngine()
        )

        # =====================================================
        # PORTFOLIO / EVALUATION
        # =====================================================

        self.portfolio_rebuilder = (
            PortfolioRebuilder(
                account_storage=(
                    self.account_storage
                ),
                trading_storage=(
                    self.trading_storage
                ),
            )
        )

        self.portfolio_report_service = (
            PortfolioReportService(
                portfolio_rebuilder=(
                    self.portfolio_rebuilder
                ),
                trading_storage=(
                    self.trading_storage
                ),
                market_price_fetcher=(
                    self._fetch_reporting_price
                ),
            )
        )

        self.equity_tracker = (
            EquityTracker(
                portfolio_report_service=(
                    self.portfolio_report_service
                ),
                equity_storage=(
                    self.equity_storage
                ),
                account_id="model1-paper",
                model_version=(
                    config.model_version
                ),
            )
        )

        self.benchmark_service = (
            BenchmarkService(
                market_data_fetcher=(
                    self._fetch_benchmark_data
                ),
                symbol=(
                    config.benchmark_symbol
                ),
            )
        )

        self.cash_benchmark_service = (
            CashBenchmarkService()
        )

        self.equal_weight_benchmark_service = (
            EqualWeightBenchmarkService(
                market_data_fetcher=(
                    self._fetch_benchmark_data
                ),
                symbols=(
                    config.tickers
                ),
            )
        )

        self.performance_metric_service = (
            PerformanceMetricService()
        )

        self.evaluation_report_service = (
            EvaluationReportService(
                benchmark_service=(
                    self.benchmark_service
                ),
                cash_benchmark_service=(
                    self.cash_benchmark_service
                ),
                equal_weight_benchmark_service=(
                    self.equal_weight_benchmark_service
                ),
                performance_metric_service=(
                    self.performance_metric_service
                ),
            )
        )

        self.report_output_directory = (
            Path(__file__).resolve().parent
            / "reports"
        )

        self.report_export_service = (
            ReportExportService(
                self.report_output_directory
            )
        )

        self.report_chart_service = (
            ReportChartService(
                self.report_output_directory
            )
        )

        self.report_bundle_service = (
            ReportBundleService(
                export_service=(
                    self.report_export_service
                ),
                chart_service=(
                    self.report_chart_service
                ),
            )
        )

        # =====================================================
        # DECISION
        # =====================================================

        self.decision_pipeline = (
            DecisionPipeline(
                account_storage=(
                    self.account_storage
                ),
                trading_storage=(
                    self.trading_storage
                ),
                signal_engine=(
                    self.signal_engine
                ),
                position_sizer=(
                    self.position_sizer
                ),
                risk_engine=(
                    self.risk_engine
                ),
            )
        )

        self.execution_service = (
            ExecutionService(
                account_storage=(
                    self.account_storage
                ),
                trading_storage=(
                    self.trading_storage
                ),
                risk_engine=(
                    self.risk_engine
                ),
            )
        )

        self.decision_coordinator = (
            DecisionExecutionCoordinator(
                execution_service=(
                    self.execution_service
                )
            )
        )

        self.decision_orchestrator = (
            DailyDecisionOrchestrator(
                market_storage=(
                    self.market_storage
                ),
                decision_pipeline=(
                    self.decision_pipeline
                ),
                coordinator=(
                    self.decision_coordinator
                ),
                model_version=(
                    config.model_version
                ),
            )
        )

        self.decision_batch_runner = (
            DailyBatchRunner(
                tickers=(
                    config.tickers
                ),
                market_data_fetcher=(
                    self._fetch_decision_market_data
                ),
                quality_report_builder=(
                    self._build_decision_quality_report
                ),
                decision_orchestrator=(
                    self.decision_orchestrator
                ),
            )
        )

        self.decision_runner = (
            DailyDecisionRunner(
                batch_runner=(
                    self.decision_batch_runner
                )
            )
        )

        # =====================================================
        # EXECUTION
        # =====================================================

        self.execution_observation_validator = (
            ExecutionObservationValidator(
                calendar_name="NYSE"
            )
        )

        self.execution_orchestrator = (
            ExecutionOrchestrator(
                market_storage=(
                    self.market_storage
                ),
                trading_storage=(
                    self.trading_storage
                ),
                execution_service=(
                    self.execution_service
                ),
                execution_attempt_storage=(
                    self.execution_attempt_storage
                ),
                observation_validator=(
                    self.execution_observation_validator
                ),
            )
        )

    # =========================================================
    # DECISION MARKET DATA
    # =========================================================

    def _fetch_decision_market_data(
        self,
        ticker: str,
    ) -> MarketDataResult:

        normalized = (
            ticker.strip().upper()
        )

        cached = (
            self._decision_market_cache
            .get(
                normalized
            )
        )

        if cached is not None:
            return cached

        result = (
            self.market_provider
            .get_daily_history(
                ticker=normalized,
                period=(
                    self.config
                    .decision_history_period
                ),
            )
        )

        self._decision_market_cache[
            normalized
        ] = result

        return result

    def _build_decision_quality_report(
        self,
        result: MarketDataResult,
    ):

        return (
            self.quality_validator
            .validate(
                result
            )
        )

    # =========================================================
    # REPORTING PRICE
    # =========================================================

    def _fetch_reporting_price(
        self,
        ticker: str,
    ) -> Decimal:

        result = (
            self.market_provider
            .get_daily_history(
                ticker=(
                    ticker.strip().upper()
                ),
                period="5d",
            )
        )

        quality_report = (
            self.quality_validator
            .validate(
                result
            )
        )

        if not quality_report.safe_to_use:
            raise RuntimeError(
                f"Market data for {ticker} "
                "failed portfolio-report "
                "quality checks."
            )

        if result.data.empty:
            raise RuntimeError(
                f"No reporting data "
                f"available for {ticker}."
            )

        if (
            "Close"
            not in result.data.columns
        ):
            raise RuntimeError(
                f"Reporting data for {ticker} "
                "has no Close column."
            )

        value = Decimal(
            str(
                result.data[
                    "Close"
                ].iloc[-1]
            )
        )

        if value <= 0:
            raise RuntimeError(
                f"Reporting price for {ticker} "
                "must be positive."
            )

        return value

    # =========================================================
    # BENCHMARK DATA
    # =========================================================

    def _fetch_benchmark_data(
        self,
        symbol: str,
    ) -> MarketDataResult:

        result = (
            self.market_provider
            .get_daily_history(
                ticker=(
                    symbol.strip().upper()
                ),
                period="1y",
            )
        )

        quality_report = (
            self.quality_validator
            .validate(
                result
            )
        )

        if not quality_report.safe_to_use:
            raise RuntimeError(
                f"Benchmark data for {symbol} "
                "failed quality checks."
            )

        if (
            "Adj Close"
            not in result.data.columns
        ):
            raise RuntimeError(
                f"Benchmark data for {symbol} "
                "requires Adj Close."
            )

        return result

    # =========================================================
    # DECISION SUPPORT
    # =========================================================

    def _build_market_prices(
        self,
    ) -> dict[str, Decimal]:

        prices: dict[
            str,
            Decimal,
        ] = {}

        for ticker in self.config.tickers:

            try:

                result = (
                    self._fetch_decision_market_data(
                        ticker
                    )
                )

                if result.data.empty:
                    continue

                if (
                    "Close"
                    not in result.data.columns
                ):
                    continue

                price = Decimal(
                    str(
                        result.data[
                            "Close"
                        ].iloc[-1]
                    )
                )

                if price <= 0:
                    continue

                prices[
                    ticker
                ] = price

            except Exception:
                continue

        return prices

    def _build_order_id_factory(
        self,
        decision_timestamp: datetime,
    ):

        source_date = (
            decision_timestamp
            .astimezone(
                NEW_YORK
            )
            .date()
            .isoformat()
        )

        model = (
            self.config
            .model_version
            .replace(
                " ",
                "-",
            )
        )

        def factory(
            ticker: str,
        ) -> str:

            return (
                f"{model}-"
                f"{source_date}-"
                f"{ticker.strip().upper()}"
            )

        return factory

    def run_decision(
        self,
        decision_timestamp: datetime,
    ):

        self._decision_market_cache = {}

        market_prices = (
            self._build_market_prices()
        )

        return (
            self.decision_runner.run(
                decision_timestamp=(
                    decision_timestamp
                ),
                market_prices=(
                    market_prices
                ),
                order_id_factory=(
                    self._build_order_id_factory(
                        decision_timestamp
                    )
                ),
            )
        )

    # =========================================================
    # REPORTING / EVALUATION
    # =========================================================

    def get_portfolio_report(
        self,
    ) -> PortfolioReport:

        return (
            self.portfolio_report_service
            .build()
        )

    def record_equity_snapshot(
        self,
        valuation_session: date,
    ) -> EquityTrackingResult:

        return (
            self.equity_tracker
            .record(
                valuation_session
            )
        )

    def get_equity_history(
        self,
    ):

        return (
            self.equity_storage
            .list_snapshots(
                account_id="model1-paper",
                model_version=(
                    self.config
                    .model_version
                ),
            )
        )

    def get_benchmark_comparison(
        self,
    ) -> BenchmarkComparison:

        history = (
            self.get_equity_history()
        )

        return (
            self.benchmark_service
            .compare(
                history
            )
        )

    def get_equal_weight_benchmark_comparison(
        self,
    ) -> EqualWeightBenchmarkComparison:

        history = (
            self.get_equity_history()
        )

        return (
            self.equal_weight_benchmark_service
            .compare(
                history
            )
        )

    def get_performance_metrics(
        self,
    ) -> PerformanceMetrics:

        history = (
            self.get_equity_history()
        )

        return (
            self.performance_metric_service
            .calculate(
                history
            )
        )

    def get_evaluation_report(
        self,
    ) -> EvaluationReport:

        history = (
            self.get_equity_history()
        )

        return (
            self.evaluation_report_service
            .build(
                history
            )
        )

    def export_report(
        self,
    ) -> ReportBundleResult:

        history = (
            self.get_equity_history()
        )

        evaluation_report = (
            self.evaluation_report_service
            .build(
                history
            )
        )

        benchmark_comparison = (
            self.benchmark_service
            .compare(
                history
            )
        )

        equal_weight_comparison = (
            self.equal_weight_benchmark_service
            .compare(
                history
            )
        )

        return (
            self.report_bundle_service
            .create(
                equity_history=(
                    history
                ),
                evaluation_report=(
                    evaluation_report
                ),
                benchmark_comparison=(
                    benchmark_comparison
                ),
                equal_weight_comparison=(
                    equal_weight_comparison
                ),
            )
        )

    # =========================================================
    # EXECUTION
    # =========================================================

    def _build_execution_runner(
        self,
        execution_session: date,
    ):

        provider = (
            self.execution_provider_factory(
                execution_session=(
                    execution_session
                )
            )
        )

        market_cache: dict[
            str,
            MarketDataResult,
        ] = {}

        def fetch(
            ticker: str,
        ) -> MarketDataResult:

            normalized = (
                ticker.strip().upper()
            )

            cached = (
                market_cache.get(
                    normalized
                )
            )

            if cached is not None:
                return cached

            result = (
                provider.get_market_data(
                    normalized
                )
            )

            market_cache[
                normalized
            ] = result

            return result

        batch_runner = (
            PendingExecutionBatchRunner(
                trading_storage=(
                    self.trading_storage
                ),
                execution_orchestrator=(
                    self.execution_orchestrator
                ),
                market_data_fetcher=(
                    fetch
                ),
                quality_report_builder=(
                    provider
                    .build_quality_report
                ),
                observation_time_builder=(
                    provider
                    .observation_time
                ),
            )
        )

        daily_runner = (
            DailyExecutionRunner(
                pending_order_query=(
                    self.pending_order_query
                ),
                execution_batch_runner=(
                    batch_runner
                ),
            )
        )

        return (
            daily_runner,
            fetch,
            market_cache,
        )

    def _build_execution_market_prices(
        self,
        fetch,
    ) -> dict[str, Decimal]:

        prices: dict[
            str,
            Decimal,
        ] = {}

        for ticker in self.config.tickers:

            try:

                result = fetch(
                    ticker
                )

                if result.data.empty:
                    continue

                if (
                    "Open"
                    not in result.data.columns
                ):
                    continue

                price = Decimal(
                    str(
                        result.data[
                            "Open"
                        ].iloc[0]
                    )
                )

                if price <= 0:
                    continue

                prices[
                    ticker
                ] = price

            except Exception:
                continue

        return prices

    def run_execution(
        self,
        execution_session: date,
    ):

        due_orders = (
            self.pending_order_query
            .find_for_session(
                execution_session
            )
        )

        if not due_orders:

            (
                empty_runner,
                _,
                _,
            ) = (
                self._build_execution_runner(
                    execution_session
                )
            )

            return (
                empty_runner.run(
                    execution_session=(
                        execution_session
                    )
                )
            )

        (
            execution_runner,
            fetch,
            _,
        ) = (
            self._build_execution_runner(
                execution_session
            )
        )

        execution_prices = (
            self._build_execution_market_prices(
                fetch
            )
        )

        return (
            execution_runner.run(
                execution_session=(
                    execution_session
                ),
                execution_market_prices=(
                    execution_prices
                ),
                valuation_prices=(
                    execution_prices
                ),
            )
        )

    # =========================================================
    # STATUS
    # =========================================================

    def _order_status_counts(
        self,
    ) -> dict[str, int]:

        engine = (
            create_sqlite_engine(
                self.config.database_path
            )
        )

        with engine.connect() as connection:

            rows = (
                connection.execute(
                    text(
                        """
                        SELECT
                            status,
                            COUNT(*) AS count
                        FROM paper_orders
                        GROUP BY status
                        """
                    )
                )
                .mappings()
                .all()
            )

        return {
            str(
                row[
                    "status"
                ]
            ): int(
                row[
                    "count"
                ]
            )
            for row in rows
        }

    def get_status(
        self,
    ) -> StatusSummary:

        account = (
            self.account_storage
            .get_account()
        )

        status_counts = (
            self._order_status_counts()
        )

        account_id = None
        starting_cash = None

        if account is not None:

            account_id = getattr(
                account,
                "account_id",
                "model1-paper",
            )

            starting_cash = getattr(
                account,
                "starting_cash",
                None,
            )

        return StatusSummary(
            account_id=account_id,
            starting_cash=starting_cash,
            total_orders=(
                self.trading_storage
                .count_orders()
            ),
            pending_orders=(
                status_counts.get(
                    "PENDING",
                    0,
                )
            ),
            filled_orders=(
                status_counts.get(
                    "FILLED",
                    0,
                )
            ),
            rejected_orders=(
                status_counts.get(
                    "REJECTED",
                    0,
                )
            ),
            total_fills=(
                self.trading_storage
                .count_fills()
            ),
            portfolio_snapshots=(
                self.trading_storage
                .count_portfolio_snapshots()
            ),
            execution_attempts=(
                self.execution_attempt_storage
                .count_attempts()
            ),
        )


def build_live_runtime(
    database_path: (
        str
        | Path
        | None
    ) = None,
    execution_provider_factory: (
        Callable[..., object]
        | None
    ) = None,
) -> LiveTradingRuntime:

    if database_path is None:

        database_path = (
            get_default_database_path()
        )

    config = RuntimeConfiguration(
        database_path=Path(
            database_path
        ),
        tickers=(
            _load_tickers()
        ),
        model_version=(
            _load_model_version()
        ),
        starting_cash=(
            _load_starting_cash()
        ),
        benchmark_symbol=(
            _load_benchmark_symbol()
        ),
    )

    return LiveTradingRuntime(
        config=config,
        execution_provider_factory=(
            execution_provider_factory
        ),
    )