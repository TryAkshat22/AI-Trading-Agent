from __future__ import annotations

from datetime import (
    date,
    datetime,
    timezone,
)
from decimal import Decimal

import pandas as pd
import pytest

from database.account_storage import (
    AccountStorage,
)
from database.execution_attempt_storage import (
    ExecutionAttemptOutcome,
    ExecutionAttemptStorage,
)
from database.storage import (
    MarketDataStorage,
)
from database.trading_storage import (
    TradingStorage,
)
from services.data_quality import (
    DataQualityReport,
)
from services.market_data import (
    MarketDataResult,
)
from trading.execution_observation import (
    ExecutionObservationTooLateError,
    ExecutionTickerMismatchError,
)
from trading.execution_orchestrator import (
    ExecutionOrchestrator,
    StoredOrderMissingError,
)
from trading.execution_service import (
    ExecutionRiskRejectedError,
    ExecutionService,
)
from trading.orders import (
    OrderSide,
    OrderStatus,
)
from trading.paper_broker import (
    BrokerConfig,
)


def make_market_result(
    *,
    ticker: str = "AAPL",
    open_price: float = 100.0,
    retrieved_at: datetime | None = None,
) -> MarketDataResult:

    if retrieved_at is None:
        retrieved_at = datetime(
            2026,
            9,
            8,
            13,
            30,
            30,
            tzinfo=timezone.utc,
        )

    data = pd.DataFrame(
        {
            "Open": [
                open_price
            ],
            "High": [
                open_price + 5
            ],
            "Low": [
                max(
                    open_price - 5,
                    0.01,
                )
            ],
            "Close": [
                open_price + 2
            ],
            "Adj Close": [
                open_price + 2
            ],
            "Volume": [
                1_000_000
            ],
        },
        index=pd.to_datetime(
            [
                "2026-09-08",
            ]
        ),
    )

    return MarketDataResult(
        ticker=ticker,
        data=data,
        provider=(
            "execution-orchestrator-test"
        ),
        retrieved_at_utc=(
            retrieved_at
        ),
    )


def make_quality_report(
    ticker: str = "AAPL",
) -> DataQualityReport:

    return DataQualityReport(
        ticker=ticker,
        checked_at_utc=datetime(
            2026,
            9,
            8,
            13,
            31,
            0,
            tzinfo=timezone.utc,
        ),
        latest_data_session=date(
            2026,
            9,
            8,
        ),
        latest_expected_completed_session=date(
            2026,
            9,
            8,
        ),
        issues=(),
    )


def make_system(
    tmp_path,
):

    database_path = (
        tmp_path
        / "test.db"
    )

    accounts = AccountStorage(
        database_path
    )

    trades = TradingStorage(
        database_path
    )

    market_storage = (
        MarketDataStorage(
            database_path
        )
    )

    attempts = ExecutionAttemptStorage(
        database_path
    )

    accounts.initialize()
    trades.initialize()
    market_storage.initialize()

    # Must happen after paper_orders and
    # ingestion_runs exist.
    attempts.initialize()

    accounts.create_account(
        10_000
    )

    execution_service = (
        ExecutionService(
            account_storage=accounts,
            trading_storage=trades,
            broker_config=BrokerConfig(
                slippage_bps=Decimal(
                    "0"
                ),
                fee_per_trade=Decimal(
                    "0"
                ),
            ),
        )
    )

    orchestrator = (
        ExecutionOrchestrator(
            market_storage=(
                market_storage
            ),
            trading_storage=(
                trades
            ),
            execution_service=(
                execution_service
            ),
            execution_attempt_storage=(
                attempts
            ),
        )
    )

    return (
        accounts,
        trades,
        market_storage,
        attempts,
        execution_service,
        orchestrator,
    )


def create_pending_order(
    execution_service,
    *,
    order_id: str = "order-1",
    quantity: int = 5,
):

    execution_service.prepare_order(
        ticker="AAPL",
        side=OrderSide.BUY,
        quantity=quantity,
        signal_timestamp=datetime(
            2026,
            9,
            4,
            21,
            0,
            tzinfo=timezone.utc,
        ),
        order_id=order_id,
    )


def test_valid_execution_has_attempt_lineage(
    tmp_path,
):

    (
        _,
        trades,
        market_storage,
        attempts,
        execution_service,
        orchestrator,
    ) = make_system(
        tmp_path
    )

    create_pending_order(
        execution_service,
        order_id="safe-order",
        quantity=5,
    )

    result = orchestrator.execute(
        order_id="safe-order",
        market_result=(
            make_market_result(
                open_price=100.0
            )
        ),
        quality_report=(
            make_quality_report()
        ),
        execution_observed_at=datetime(
            2026,
            9,
            8,
            13,
            31,
            0,
            tzinfo=timezone.utc,
        ),
        valuation_prices={
            "AAPL": Decimal(
                "100"
            ),
        },
        recorded_at_utc=datetime(
            2026,
            9,
            8,
            13,
            31,
            5,
            tzinfo=timezone.utc,
        ),
    )

    assert (
        trades.get_order_status(
            "safe-order"
        )
        == OrderStatus.FILLED.value
    )

    assert (
        trades.count_fills()
        == 1
    )

    assert (
        attempts.count_attempts()
        == 1
    )

    records = (
        attempts.list_attempts_for_order(
            "safe-order"
        )
    )

    assert len(records) == 1

    attempt = records[0]

    assert (
        attempt.outcome
        == ExecutionAttemptOutcome.FILLED
    )

    assert (
        attempt.execution_run_id
        == result.execution_run_id
    )

    fills = trades.list_fills()

    assert (
        fills[0].execution_run_id
        == result.execution_run_id
    )

    assert (
        market_storage
        .count_ingestion_runs()
        == 1
    )


def test_risk_rejection_has_execution_lineage(
    tmp_path,
):

    (
        _,
        trades,
        market_storage,
        attempts,
        execution_service,
        orchestrator,
    ) = make_system(
        tmp_path
    )

    create_pending_order(
        execution_service,
        order_id="gap-order",
        quantity=5,
    )

    with pytest.raises(
        ExecutionRiskRejectedError
    ):
        orchestrator.execute(
            order_id="gap-order",
            market_result=(
                make_market_result(
                    open_price=2_000.0
                )
            ),
            quality_report=(
                make_quality_report()
            ),
            execution_observed_at=datetime(
                2026,
                9,
                8,
                13,
                31,
                0,
                tzinfo=timezone.utc,
            ),
        )

    assert (
        trades.get_order_status(
            "gap-order"
        )
        == OrderStatus.REJECTED.value
    )

    assert (
        trades.count_fills()
        == 0
    )

    records = (
        attempts.list_attempts_for_order(
            "gap-order"
        )
    )

    assert len(records) == 1

    attempt = records[0]

    assert (
        attempt.outcome
        == ExecutionAttemptOutcome.REJECTED
    )

    assert (
        attempt.execution_run_id
        is not None
    )

    assert (
        attempt.error_type
        == "ExecutionRiskRejectedError"
    )

    # The rejected execution observation remains.
    assert (
        market_storage
        .count_ingestion_runs()
        == 1
    )


def test_late_observation_creates_no_attempt(
    tmp_path,
):

    (
        _,
        trades,
        market_storage,
        attempts,
        execution_service,
        orchestrator,
    ) = make_system(
        tmp_path
    )

    create_pending_order(
        execution_service,
        order_id="late-order",
    )

    with pytest.raises(
        ExecutionObservationTooLateError
    ):
        orchestrator.execute(
            order_id="late-order",
            market_result=(
                make_market_result()
            ),
            quality_report=(
                make_quality_report()
            ),
            execution_observed_at=datetime(
                2026,
                9,
                8,
                13,
                36,
                0,
                tzinfo=timezone.utc,
            ),
        )

    assert (
        attempts.count_attempts()
        == 0
    )

    assert (
        market_storage
        .count_ingestion_runs()
        == 0
    )

    assert (
        trades.get_order_status(
            "late-order"
        )
        == OrderStatus.PENDING.value
    )


def test_wrong_ticker_creates_no_attempt(
    tmp_path,
):

    (
        _,
        trades,
        market_storage,
        attempts,
        execution_service,
        orchestrator,
    ) = make_system(
        tmp_path
    )

    create_pending_order(
        execution_service,
        order_id="ticker-order",
    )

    with pytest.raises(
        ExecutionTickerMismatchError
    ):
        orchestrator.execute(
            order_id="ticker-order",
            market_result=(
                make_market_result(
                    ticker="MSFT"
                )
            ),
            quality_report=(
                make_quality_report(
                    ticker="MSFT"
                )
            ),
            execution_observed_at=datetime(
                2026,
                9,
                8,
                13,
                31,
                0,
                tzinfo=timezone.utc,
            ),
        )

    assert (
        attempts.count_attempts()
        == 0
    )

    assert (
        market_storage
        .count_ingestion_runs()
        == 0
    )

    assert (
        trades.get_order_status(
            "ticker-order"
        )
        == OrderStatus.PENDING.value
    )


def test_missing_order_creates_no_attempt(
    tmp_path,
):

    (
        _,
        _,
        market_storage,
        attempts,
        _,
        orchestrator,
    ) = make_system(
        tmp_path
    )

    with pytest.raises(
        StoredOrderMissingError
    ):
        orchestrator.execute(
            order_id="missing",
            market_result=(
                make_market_result()
            ),
            quality_report=(
                make_quality_report()
            ),
            execution_observed_at=datetime(
                2026,
                9,
                8,
                13,
                31,
                0,
                tzinfo=timezone.utc,
            ),
        )

    assert (
        attempts.count_attempts()
        == 0
    )

    assert (
        market_storage
        .count_ingestion_runs()
        == 0
    )