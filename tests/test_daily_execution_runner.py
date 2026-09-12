from __future__ import annotations

from datetime import (
    date,
    datetime,
    timezone,
)
from types import SimpleNamespace

import pytest

from database.pending_order_query import (
    PendingOrderReference,
)
from trading.daily_execution_runner import (
    DailyExecutionRunner,
)


TARGET_SESSION = date(
    2026,
    9,
    8,
)


class FakePendingOrderQuery:

    def __init__(
        self,
        records,
    ) -> None:

        self.records = tuple(
            records
        )

        self.calls = []

    def find_for_session(
        self,
        execution_session,
    ):

        self.calls.append(
            execution_session
        )

        return self.records


class FakeExecutionBatchRunner:

    def __init__(
        self,
        *,
        filled=0,
        rejected=0,
        failed=0,
        skipped=0,
    ) -> None:

        self.calls = []

        self.result = (
            SimpleNamespace(
                filled_orders=filled,
                rejected_orders=rejected,
                failed_orders=failed,
                skipped_orders=skipped,
            )
        )

    def run(
        self,
        **kwargs,
    ):

        self.calls.append(
            kwargs
        )

        return self.result


def make_reference(
    order_id: str,
    ticker: str,
) -> PendingOrderReference:

    return PendingOrderReference(
        order_id=order_id,
        ticker=ticker,
        execution_session=(
            TARGET_SESSION
        ),
        model_version=(
            "model-1"
        ),
    )


def test_no_pending_orders_returns_no_work():

    query = FakePendingOrderQuery(
        []
    )

    batch = FakeExecutionBatchRunner()

    runner = DailyExecutionRunner(
        pending_order_query=query,
        execution_batch_runner=batch,
    )

    result = runner.run(
        execution_session=(
            TARGET_SESSION
        )
    )

    assert (
        result.had_work
        is False
    )

    assert (
        result.discovered_order_count
        == 0
    )

    assert (
        result.batch_result
        is None
    )

    assert (
        result.filled_orders
        == 0
    )

    assert (
        result.rejected_orders
        == 0
    )

    assert (
        result.failed_orders
        == 0
    )

    assert (
        result.skipped_orders
        == 0
    )

    assert (
        len(
            batch.calls
        )
        == 0
    )


def test_discovered_orders_are_forwarded():

    query = FakePendingOrderQuery(
        [
            make_reference(
                "order-1",
                "AAPL",
            ),
            make_reference(
                "order-2",
                "MSFT",
            ),
        ]
    )

    batch = FakeExecutionBatchRunner(
        filled=2
    )

    runner = DailyExecutionRunner(
        pending_order_query=query,
        execution_batch_runner=batch,
    )

    result = runner.run(
        execution_session=(
            TARGET_SESSION
        )
    )

    assert (
        result.had_work
        is True
    )

    assert (
        result.discovered_order_count
        == 2
    )

    assert (
        len(
            batch.calls
        )
        == 1
    )

    assert (
        batch.calls[0][
            "order_ids"
        ]
        == (
            "order-1",
            "order-2",
        )
    )

    assert (
        batch.calls[0][
            "execution_session"
        ]
        == TARGET_SESSION
    )


def test_batch_counts_are_exposed():

    query = FakePendingOrderQuery(
        [
            make_reference(
                "order-1",
                "AAPL",
            ),
            make_reference(
                "order-2",
                "MSFT",
            ),
            make_reference(
                "order-3",
                "NVDA",
            ),
            make_reference(
                "order-4",
                "AMZN",
            ),
        ]
    )

    batch = FakeExecutionBatchRunner(
        filled=1,
        rejected=1,
        failed=1,
        skipped=1,
    )

    runner = DailyExecutionRunner(
        pending_order_query=query,
        execution_batch_runner=batch,
    )

    result = runner.run(
        execution_session=(
            TARGET_SESSION
        )
    )

    assert (
        result.filled_orders
        == 1
    )

    assert (
        result.rejected_orders
        == 1
    )

    assert (
        result.failed_orders
        == 1
    )

    assert (
        result.skipped_orders
        == 1
    )


def test_execution_market_prices_are_forwarded():

    query = FakePendingOrderQuery(
        [
            make_reference(
                "order-1",
                "AAPL",
            )
        ]
    )

    batch = FakeExecutionBatchRunner()

    runner = DailyExecutionRunner(
        pending_order_query=query,
        execution_batch_runner=batch,
    )

    prices = {
        "AAPL": 100,
        "MSFT": 200,
    }

    runner.run(
        execution_session=(
            TARGET_SESSION
        ),
        execution_market_prices=prices,
    )

    assert (
        batch.calls[0][
            "execution_market_prices"
        ]
        == prices
    )


def test_valuation_prices_are_forwarded():

    query = FakePendingOrderQuery(
        [
            make_reference(
                "order-1",
                "AAPL",
            )
        ]
    )

    batch = FakeExecutionBatchRunner()

    runner = DailyExecutionRunner(
        pending_order_query=query,
        execution_batch_runner=batch,
    )

    prices = {
        "AAPL": 100,
        "MSFT": 200,
    }

    runner.run(
        execution_session=(
            TARGET_SESSION
        ),
        valuation_prices=prices,
    )

    assert (
        batch.calls[0][
            "valuation_prices"
        ]
        == prices
    )


def test_recorded_time_is_forwarded():

    query = FakePendingOrderQuery(
        [
            make_reference(
                "order-1",
                "AAPL",
            )
        ]
    )

    batch = FakeExecutionBatchRunner()

    runner = DailyExecutionRunner(
        pending_order_query=query,
        execution_batch_runner=batch,
    )

    recorded_at = datetime(
        2026,
        9,
        8,
        13,
        31,
        5,
        tzinfo=timezone.utc,
    )

    runner.run(
        execution_session=(
            TARGET_SESSION
        ),
        recorded_at_utc=(
            recorded_at
        ),
    )

    assert (
        batch.calls[0][
            "recorded_at_utc"
        ]
        == recorded_at
    )


def test_discovery_uses_exact_session():

    query = FakePendingOrderQuery(
        []
    )

    batch = FakeExecutionBatchRunner()

    runner = DailyExecutionRunner(
        pending_order_query=query,
        execution_batch_runner=batch,
    )

    runner.run(
        execution_session=(
            TARGET_SESSION
        )
    )

    assert (
        query.calls
        == [
            TARGET_SESSION
        ]
    )


def test_invalid_session_type_is_rejected():

    query = FakePendingOrderQuery(
        []
    )

    batch = FakeExecutionBatchRunner()

    runner = DailyExecutionRunner(
        pending_order_query=query,
        execution_batch_runner=batch,
    )

    with pytest.raises(
        TypeError
    ):

        runner.run(
            execution_session=(
                "2026-09-08"
            )
        )

    assert (
        len(
            query.calls
        )
        == 0
    )

    assert (
        len(
            batch.calls
        )
        == 0
    )