from __future__ import annotations

from datetime import (
    date,
    datetime,
    timezone,
)
from types import SimpleNamespace

import pytest

from trading.orders import (
    OrderStatus,
)
from trading.pending_execution_batch_runner import (
    ExecutionBatchOutcome,
    InvalidExecutionBatchError,
    PendingExecutionBatchRunner,
)


TARGET_SESSION = date(
    2026,
    9,
    8,
)


class StoredOrder:

    def __init__(
        self,
        order_id: str,
        ticker: str,
        execution_session: date = TARGET_SESSION,
    ) -> None:

        self.order_id = order_id
        self.ticker = ticker
        self.execution_session = execution_session


class FakeTradingStorage:

    def __init__(
        self,
        orders: dict[str, StoredOrder],
        statuses: dict[str, str],
    ) -> None:

        self.orders = dict(
            orders
        )

        self.statuses = dict(
            statuses
        )

    def get_order(
        self,
        order_id: str,
    ):

        return self.orders.get(
            order_id
        )

    def get_order_status(
        self,
        order_id: str,
    ):

        return self.statuses.get(
            order_id
        )


class FakeMarketResult:

    def __init__(
        self,
        ticker: str,
    ) -> None:

        self.ticker = ticker

        self.retrieved_at_utc = datetime(
            2026,
            9,
            8,
            13,
            30,
            30,
            tzinfo=timezone.utc,
        )


class FakeQualityReport:

    def __init__(
        self,
        ticker: str,
    ) -> None:

        self.ticker = ticker


class FakeExecutionOrchestrator:

    def __init__(
        self,
        trading_storage: FakeTradingStorage,
        behavior: dict[str, str] | None = None,
    ) -> None:

        self.trading_storage = (
            trading_storage
        )

        self.behavior = (
            behavior
            if behavior is not None
            else {}
        )

        self.calls: list[dict] = []

    def execute(
        self,
        **kwargs,
    ):

        self.calls.append(
            kwargs
        )

        order_id = kwargs[
            "order_id"
        ]

        behavior = self.behavior.get(
            order_id,
            "FILL",
        )

        if behavior == "FILL":

            self.trading_storage.statuses[
                order_id
            ] = (
                OrderStatus.FILLED.value
            )

            return SimpleNamespace(
                execution_run_id=(
                    f"run-{order_id}"
                )
            )

        if behavior == "REJECT":

            self.trading_storage.statuses[
                order_id
            ] = (
                OrderStatus.REJECTED.value
            )

            raise RuntimeError(
                "Execution risk rejected."
            )

        if behavior == "FAIL":

            raise RuntimeError(
                "Operational execution failure."
            )

        if behavior == "FILL_THEN_ERROR":

            self.trading_storage.statuses[
                order_id
            ] = (
                OrderStatus.FILLED.value
            )

            raise RuntimeError(
                "Post-fill operational error."
            )

        raise RuntimeError(
            "Unknown fake behavior."
        )


def make_runner(
    *,
    orders: dict[str, StoredOrder] | None = None,
    statuses: dict[str, str] | None = None,
    behavior: dict[str, str] | None = None,
    fetcher=None,
    quality_builder=None,
):

    if orders is None:

        orders = {
            "order-1": StoredOrder(
                "order-1",
                "AAPL",
            ),
        }

    if statuses is None:

        statuses = {
            order_id: (
                OrderStatus.PENDING.value
            )
            for order_id in orders
        }

    storage = FakeTradingStorage(
        orders=orders,
        statuses=statuses,
    )

    orchestrator = (
        FakeExecutionOrchestrator(
            trading_storage=storage,
            behavior=behavior,
        )
    )

    if fetcher is None:

        def fetcher(
            ticker: str,
        ):
            return FakeMarketResult(
                ticker
            )

    if quality_builder is None:

        def quality_builder(
            result,
        ):
            return FakeQualityReport(
                result.ticker
            )

    runner = PendingExecutionBatchRunner(
        trading_storage=storage,
        execution_orchestrator=(
            orchestrator
        ),
        market_data_fetcher=fetcher,
        quality_report_builder=(
            quality_builder
        ),
        observation_time_builder=(
            lambda result: datetime(
                2026,
                9,
                8,
                13,
                31,
                tzinfo=timezone.utc,
            )
        ),
    )

    return (
        storage,
        orchestrator,
        runner,
    )


def test_all_pending_orders_can_fill():

    orders = {
        "order-1": StoredOrder(
            "order-1",
            "AAPL",
        ),
        "order-2": StoredOrder(
            "order-2",
            "MSFT",
        ),
    }

    _, orchestrator, runner = (
        make_runner(
            orders=orders
        )
    )

    result = runner.run(
        order_ids=[
            "order-1",
            "order-2",
        ],
        execution_session=(
            TARGET_SESSION
        ),
    )

    assert (
        result.total_orders
        == 2
    )

    assert (
        result.filled_orders
        == 2
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
            orchestrator.calls
        )
        == 2
    )


def test_rejection_does_not_stop_other_orders():

    orders = {
        "order-1": StoredOrder(
            "order-1",
            "AAPL",
        ),
        "order-2": StoredOrder(
            "order-2",
            "MSFT",
        ),
        "order-3": StoredOrder(
            "order-3",
            "NVDA",
        ),
    }

    behavior = {
        "order-2": "REJECT",
    }

    _, orchestrator, runner = (
        make_runner(
            orders=orders,
            behavior=behavior,
        )
    )

    result = runner.run(
        order_ids=[
            "order-1",
            "order-2",
            "order-3",
        ],
        execution_session=(
            TARGET_SESSION
        ),
    )

    assert (
        result.filled_orders
        == 2
    )

    assert (
        result.rejected_orders
        == 1
    )

    assert (
        result.failed_orders
        == 0
    )

    assert (
        len(
            orchestrator.calls
        )
        == 3
    )


def test_operational_failure_does_not_stop_batch():

    orders = {
        "order-1": StoredOrder(
            "order-1",
            "AAPL",
        ),
        "order-2": StoredOrder(
            "order-2",
            "MSFT",
        ),
    }

    behavior = {
        "order-1": "FAIL",
    }

    _, orchestrator, runner = (
        make_runner(
            orders=orders,
            behavior=behavior,
        )
    )

    result = runner.run(
        order_ids=[
            "order-1",
            "order-2",
        ],
        execution_session=(
            TARGET_SESSION
        ),
    )

    assert (
        result.failed_orders
        == 1
    )

    assert (
        result.filled_orders
        == 1
    )

    assert (
        len(
            orchestrator.calls
        )
        == 2
    )


def test_wrong_session_is_skipped():

    orders = {
        "future-order": StoredOrder(
            "future-order",
            "AAPL",
            execution_session=date(
                2026,
                9,
                9,
            ),
        ),
    }

    _, orchestrator, runner = (
        make_runner(
            orders=orders
        )
    )

    result = runner.run(
        order_ids=[
            "future-order"
        ],
        execution_session=(
            TARGET_SESSION
        ),
    )

    assert (
        result.skipped_orders
        == 1
    )

    assert (
        result.failed_orders
        == 0
    )

    assert (
        len(
            orchestrator.calls
        )
        == 0
    )


def test_nonpending_order_is_skipped():

    orders = {
        "filled-order": StoredOrder(
            "filled-order",
            "AAPL",
        ),
    }

    statuses = {
        "filled-order": (
            OrderStatus.FILLED.value
        )
    }

    _, orchestrator, runner = (
        make_runner(
            orders=orders,
            statuses=statuses,
        )
    )

    result = runner.run(
        order_ids=[
            "filled-order"
        ],
        execution_session=(
            TARGET_SESSION
        ),
    )

    assert (
        result.skipped_orders
        == 1
    )

    assert (
        result.failed_orders
        == 0
    )

    assert (
        len(
            orchestrator.calls
        )
        == 0
    )


def test_missing_order_is_failed():

    _, orchestrator, runner = (
        make_runner()
    )

    result = runner.run(
        order_ids=[
            "missing-order"
        ],
        execution_session=(
            TARGET_SESSION
        ),
    )

    assert (
        result.failed_orders
        == 1
    )

    assert (
        result.results[0]
        .error_type
        == "StoredOrderMissing"
    )

    assert (
        len(
            orchestrator.calls
        )
        == 0
    )


def test_provider_failure_does_not_stop_batch():

    orders = {
        "order-1": StoredOrder(
            "order-1",
            "AAPL",
        ),
        "order-2": StoredOrder(
            "order-2",
            "MSFT",
        ),
    }

    def fetcher(
        ticker: str,
    ):

        if ticker == "AAPL":

            raise RuntimeError(
                "Provider unavailable."
            )

        return FakeMarketResult(
            ticker
        )

    _, orchestrator, runner = (
        make_runner(
            orders=orders,
            fetcher=fetcher,
        )
    )

    result = runner.run(
        order_ids=[
            "order-1",
            "order-2",
        ],
        execution_session=(
            TARGET_SESSION
        ),
    )

    assert (
        result.failed_orders
        == 1
    )

    assert (
        result.filled_orders
        == 1
    )

    assert (
        len(
            orchestrator.calls
        )
        == 1
    )


def test_wrong_provider_ticker_fails_order():

    def fetcher(
        ticker: str,
    ):

        return FakeMarketResult(
            "MSFT"
        )

    _, orchestrator, runner = (
        make_runner(
            fetcher=fetcher
        )
    )

    result = runner.run(
        order_ids=[
            "order-1"
        ],
        execution_session=(
            TARGET_SESSION
        ),
    )

    assert (
        result.failed_orders
        == 1
    )

    assert (
        result.results[0]
        .error_type
        == "PendingExecutionBatchRunnerError"
    )

    assert (
        len(
            orchestrator.calls
        )
        == 0
    )


def test_wrong_quality_ticker_fails_order():

    def quality_builder(
        result,
    ):

        return FakeQualityReport(
            "MSFT"
        )

    _, orchestrator, runner = (
        make_runner(
            quality_builder=(
                quality_builder
            )
        )
    )

    result = runner.run(
        order_ids=[
            "order-1"
        ],
        execution_session=(
            TARGET_SESSION
        ),
    )

    assert (
        result.failed_orders
        == 1
    )

    assert (
        len(
            orchestrator.calls
        )
        == 0
    )


def test_duplicate_order_ids_are_removed():

    _, orchestrator, runner = (
        make_runner()
    )

    result = runner.run(
        order_ids=[
            "order-1",
            "order-1",
            " order-1 ",
        ],
        execution_session=(
            TARGET_SESSION
        ),
    )

    assert (
        result.total_orders
        == 1
    )

    assert (
        result.filled_orders
        == 1
    )

    assert (
        len(
            orchestrator.calls
        )
        == 1
    )


def test_empty_batch_is_rejected():

    _, _, runner = (
        make_runner()
    )

    with pytest.raises(
        InvalidExecutionBatchError
    ):

        runner.run(
            order_ids=[],
            execution_session=(
                TARGET_SESSION
            ),
        )


def test_blank_order_id_is_rejected():

    _, _, runner = (
        make_runner()
    )

    with pytest.raises(
        InvalidExecutionBatchError
    ):

        runner.run(
            order_ids=[
                "order-1",
                "   ",
            ],
            execution_session=(
                TARGET_SESSION
            ),
        )


def test_filled_then_error_is_classified_as_filled():

    orders = {
        "order-1": StoredOrder(
            "order-1",
            "AAPL",
        ),
    }

    behavior = {
        "order-1": "FILL_THEN_ERROR",
    }

    _, _, runner = (
        make_runner(
            orders=orders,
            behavior=behavior,
        )
    )

    result = runner.run(
        order_ids=[
            "order-1"
        ],
        execution_session=(
            TARGET_SESSION
        ),
    )

    assert (
        result.filled_orders
        == 1
    )

    assert (
        result.failed_orders
        == 0
    )

    assert (
        result.results[0]
        .error_type
        == "RuntimeError"
    )