from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Mapping, Sequence

from services.data_quality import (
    DataQualityReport,
)
from services.market_data import (
    MarketDataResult,
)
from trading.daily_decision_orchestrator import (
    DailyDecisionOrchestrator,
    DailyDecisionResult,
)


class DailyBatchRunnerError(Exception):
    """
    Base exception for batch-runner failures.
    """


class InvalidTickerUniverseError(
    DailyBatchRunnerError
):
    """
    Raised when the configured ticker universe
    is empty or invalid.
    """


@dataclass(frozen=True)
class TickerBatchResult:
    """
    Outcome for one ticker inside a batch.

    success=True:
        the complete decision cycle ran

    success=False:
        the ticker failed without stopping
        the rest of the batch
    """

    ticker: str

    success: bool

    decision_result: (
        DailyDecisionResult | None
    )

    error_type: str | None

    error_message: str | None

    @property
    def order_created(
        self,
    ) -> bool:

        return (
            self.success
            and self.decision_result
            is not None
            and self.decision_result
            .order_created
        )


@dataclass(frozen=True)
class DailyBatchResult:
    """
    Aggregate result for one daily decision batch.
    """

    started_at_utc: datetime

    results: tuple[
        TickerBatchResult,
        ...,
    ]

    @property
    def total_tickers(
        self,
    ) -> int:

        return len(
            self.results
        )

    @property
    def successful_tickers(
        self,
    ) -> int:

        return sum(
            1
            for result in self.results
            if result.success
        )

    @property
    def failed_tickers(
        self,
    ) -> int:

        return sum(
            1
            for result in self.results
            if not result.success
        )

    @property
    def orders_created(
        self,
    ) -> int:

        return sum(
            1
            for result in self.results
            if result.order_created
        )

    @property
    def failures(
        self,
    ) -> tuple[
        TickerBatchResult,
        ...,
    ]:

        return tuple(
            result
            for result in self.results
            if not result.success
        )


class DailyBatchRunner:
    """
    Runs the Model 1 after-close decision workflow
    across a fixed universe of tickers.

    Per ticker:

        fetch market data
                ↓
        build quality report
                ↓
        DailyDecisionOrchestrator
                ↓
        optional PENDING order

    Important behavior:

        one ticker failure
                ↓
        record failure
                ↓
        continue remaining tickers

    This class deliberately does NOT perform
    next-session execution.

    Decision batching and execution batching remain
    separate workflows because they occur at different
    times of day.
    """

    def __init__(
        self,
        tickers: Sequence[str],

        market_data_fetcher: Callable[
            [str],
            MarketDataResult,
        ],

        quality_report_builder: Callable[
            [MarketDataResult],
            DataQualityReport,
        ],

        decision_orchestrator: (
            DailyDecisionOrchestrator
        ),
    ) -> None:

        normalized_tickers = (
            self._normalize_tickers(
                tickers
            )
        )

        self.tickers = (
            normalized_tickers
        )

        self.market_data_fetcher = (
            market_data_fetcher
        )

        self.quality_report_builder = (
            quality_report_builder
        )

        self.decision_orchestrator = (
            decision_orchestrator
        )

    def run(
        self,
        decision_timestamp: datetime,

        market_prices: (
            Mapping[
                str,
                object,
            ]
            | None
        ) = None,

        order_id_factory: (
            Callable[
                [str],
                str | None,
            ]
            | None
        ) = None,

    ) -> DailyBatchResult:
        """
        Run one complete after-close decision batch.

        market_prices:
            optional portfolio valuation prices shared
            with DecisionPipeline.

        order_id_factory:
            optional deterministic order-ID creator.
            Useful later for idempotent scheduled runs.
        """

        results: list[
            TickerBatchResult
        ] = []

        batch_started = (
            decision_timestamp
        )

        shared_prices = dict(
            market_prices
            if market_prices is not None
            else {}
        )

        for ticker in self.tickers:

            try:

                ticker_result = (
                    self._run_one_ticker(
                        ticker=ticker,
                        decision_timestamp=(
                            decision_timestamp
                        ),
                        market_prices=(
                            shared_prices
                        ),
                        order_id_factory=(
                            order_id_factory
                        ),
                    )
                )

            except Exception as exc:

                results.append(
                    TickerBatchResult(
                        ticker=ticker,
                        success=False,
                        decision_result=None,
                        error_type=(
                            type(
                                exc
                            ).__name__
                        ),
                        error_message=str(
                            exc
                        ),
                    )
                )

                continue

            results.append(
                TickerBatchResult(
                    ticker=ticker,
                    success=True,
                    decision_result=(
                        ticker_result
                    ),
                    error_type=None,
                    error_message=None,
                )
            )

        return DailyBatchResult(
            started_at_utc=(
                batch_started
            ),
            results=tuple(
                results
            ),
        )

    def _run_one_ticker(
        self,
        ticker: str,
        decision_timestamp: datetime,
        market_prices: dict[
            str,
            object,
        ],
        order_id_factory: (
            Callable[
                [str],
                str | None,
            ]
            | None
        ),
    ) -> DailyDecisionResult:

        # ---------------------------------------------
        # 1. FETCH
        # ---------------------------------------------

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

        if (
            actual_ticker
            != ticker
        ):
            raise DailyBatchRunnerError(
                "Market-data provider returned "
                "the wrong ticker. "
                f"Requested: {ticker}. "
                f"Received: {actual_ticker}."
            )

        # ---------------------------------------------
        # 2. QUALITY
        # ---------------------------------------------

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

        if (
            quality_ticker
            != ticker
        ):
            raise DailyBatchRunnerError(
                "Quality report ticker does not "
                "match requested ticker. "
                f"Requested: {ticker}. "
                f"Received: {quality_ticker}."
            )

        # ---------------------------------------------
        # 3. BUILD VALUATION INPUTS
        # ---------------------------------------------

        decision_kwargs = {}

        if market_prices:

            decision_kwargs[
                "market_prices"
            ] = market_prices

        # ---------------------------------------------
        # 4. OPTIONAL ORDER ID
        # ---------------------------------------------

        order_id = None

        if order_id_factory is not None:

            order_id = (
                order_id_factory(
                    ticker
                )
            )

        # ---------------------------------------------
        # 5. REAL DECISION ORCHESTRATOR
        # ---------------------------------------------

        return (
            self.decision_orchestrator.run(
                market_result=(
                    market_result
                ),
                quality_report=(
                    quality_report
                ),
                decision_timestamp=(
                    decision_timestamp
                ),
                decision_kwargs=(
                    decision_kwargs
                ),
                order_id=(
                    order_id
                ),
            )
        )

    @staticmethod
    def _normalize_tickers(
        tickers: Sequence[str],
    ) -> tuple[str, ...]:

        normalized: list[str] = []

        seen: set[str] = set()

        for raw_ticker in tickers:

            ticker = (
                str(
                    raw_ticker
                )
                .strip()
                .upper()
            )

            if not ticker:
                raise InvalidTickerUniverseError(
                    "Ticker universe contains "
                    "an empty ticker."
                )

            if ticker in seen:
                continue

            seen.add(
                ticker
            )

            normalized.append(
                ticker
            )

        if not normalized:
            raise InvalidTickerUniverseError(
                "Ticker universe cannot be empty."
            )

        return tuple(
            normalized
        )