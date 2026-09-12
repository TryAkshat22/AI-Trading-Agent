from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Mapping

from trading.daily_batch_runner import (
    DailyBatchResult,
    DailyBatchRunner,
)


class DailyDecisionRunnerError(Exception):
    """
    Base exception for top-level daily decision runs.
    """


@dataclass(frozen=True)
class DailyDecisionRunResult:
    """
    Top-level summary of one after-close
    decision run.
    """

    decision_timestamp_utc: datetime

    batch_result: DailyBatchResult

    @property
    def total_tickers(
        self,
    ) -> int:

        return (
            self.batch_result
            .total_tickers
        )

    @property
    def successful_tickers(
        self,
    ) -> int:

        return (
            self.batch_result
            .successful_tickers
        )

    @property
    def failed_tickers(
        self,
    ) -> int:

        return (
            self.batch_result
            .failed_tickers
        )

    @property
    def orders_created(
        self,
    ) -> int:

        return (
            self.batch_result
            .orders_created
        )

    @property
    def had_failures(
        self,
    ) -> bool:

        return (
            self.failed_tickers
            > 0
        )


class DailyDecisionRunner:
    """
    Top-level after-close decision coordinator.

    Flow:

        decision timestamp
              ↓
        DailyDecisionRunner
              ↓
        DailyBatchRunner
              ↓
        ticker universe
              ↓
        market data + quality
              ↓
        DailyDecisionOrchestrator
              ↓
        optional PENDING orders

    This layer deliberately does not duplicate:

        - market-data fetching
        - quality validation
        - signal generation
        - position sizing
        - risk checks
        - persistence
        - order creation

    All of those remain in the lower,
    already-tested layers.
    """

    def __init__(
        self,
        batch_runner: DailyBatchRunner,
    ) -> None:

        self.batch_runner = (
            batch_runner
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

    ) -> DailyDecisionRunResult:
        """
        Run the complete after-close decision cycle
        for the configured ticker universe.
        """

        if not isinstance(
            decision_timestamp,
            datetime,
        ):
            raise TypeError(
                "decision_timestamp must be "
                "a datetime.datetime."
            )

        if (
            decision_timestamp.tzinfo
            is None
        ):
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
            batch_result=(
                batch_result
            ),
        )