from __future__ import annotations

from datetime import (
    datetime,
    timezone,
)
from types import SimpleNamespace

import pytest

from trading.daily_decision_runner import (
    DailyDecisionRunner,
    DailyDecisionRunnerError,
)


DECISION_TIME = datetime(
    2026,
    9,
    4,
    21,
    0,
    tzinfo=timezone.utc,
)


class FakeDailyBatchRunner:

    def __init__(
        self,
        *,
        total=3,
        successful=3,
        failed=0,
        orders=1,
    ) -> None:

        self.calls = []

        self.result = SimpleNamespace(
            total_tickers=total,
            successful_tickers=(
                successful
            ),
            failed_tickers=failed,
            orders_created=orders,
        )

    def run(
        self,
        **kwargs,
    ):

        self.calls.append(
            kwargs
        )

        return self.result


def test_runner_calls_batch_once():

    batch = FakeDailyBatchRunner()

    runner = DailyDecisionRunner(
        batch_runner=batch
    )

    runner.run(
        decision_timestamp=(
            DECISION_TIME
        )
    )

    assert (
        len(
            batch.calls
        )
        == 1
    )


def test_decision_timestamp_is_forwarded():

    batch = FakeDailyBatchRunner()

    runner = DailyDecisionRunner(
        batch_runner=batch
    )

    runner.run(
        decision_timestamp=(
            DECISION_TIME
        )
    )

    assert (
        batch.calls[0][
            "decision_timestamp"
        ]
        == DECISION_TIME
    )


def test_batch_summary_is_exposed():

    batch = FakeDailyBatchRunner(
        total=10,
        successful=8,
        failed=2,
        orders=3,
    )

    runner = DailyDecisionRunner(
        batch_runner=batch
    )

    result = runner.run(
        decision_timestamp=(
            DECISION_TIME
        )
    )

    assert (
        result.total_tickers
        == 10
    )

    assert (
        result.successful_tickers
        == 8
    )

    assert (
        result.failed_tickers
        == 2
    )

    assert (
        result.orders_created
        == 3
    )

    assert (
        result.had_failures
        is True
    )


def test_no_failures_reports_false():

    batch = FakeDailyBatchRunner(
        total=10,
        successful=10,
        failed=0,
        orders=2,
    )

    runner = DailyDecisionRunner(
        batch_runner=batch
    )

    result = runner.run(
        decision_timestamp=(
            DECISION_TIME
        )
    )

    assert (
        result.had_failures
        is False
    )


def test_market_prices_are_forwarded():

    batch = FakeDailyBatchRunner()

    runner = DailyDecisionRunner(
        batch_runner=batch
    )

    prices = {
        "AAPL": 100,
        "MSFT": 200,
    }

    runner.run(
        decision_timestamp=(
            DECISION_TIME
        ),
        market_prices=prices,
    )

    assert (
        batch.calls[0][
            "market_prices"
        ]
        == prices
    )


def test_order_id_factory_is_forwarded():

    batch = FakeDailyBatchRunner()

    runner = DailyDecisionRunner(
        batch_runner=batch
    )

    factory = (
        lambda ticker:
        f"20260904-{ticker}"
    )

    runner.run(
        decision_timestamp=(
            DECISION_TIME
        ),
        order_id_factory=(
            factory
        ),
    )

    assert (
        batch.calls[0][
            "order_id_factory"
        ]
        is factory
    )


def test_naive_timestamp_is_rejected():

    batch = FakeDailyBatchRunner()

    runner = DailyDecisionRunner(
        batch_runner=batch
    )

    with pytest.raises(
        DailyDecisionRunnerError
    ):

        runner.run(
            decision_timestamp=datetime(
                2026,
                9,
                4,
                21,
                0,
            )
        )

    assert (
        len(
            batch.calls
        )
        == 0
    )


def test_non_datetime_is_rejected():

    batch = FakeDailyBatchRunner()

    runner = DailyDecisionRunner(
        batch_runner=batch
    )

    with pytest.raises(
        TypeError
    ):

        runner.run(
            decision_timestamp=(
                "2026-09-04T21:00:00Z"
            )
        )

    assert (
        len(
            batch.calls
        )
        == 0
    )