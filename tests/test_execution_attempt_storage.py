from __future__ import annotations

from datetime import (
    date,
    datetime,
    timezone,
)

import pandas as pd
import pytest

from database.account_storage import (
    AccountStorage,
)
from database.execution_attempt_storage import (
    DuplicateExecutionAttemptError,
    ExecutionAttemptOutcome,
    ExecutionAttemptStorage,
    InvalidExecutionAttemptStateError,
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
from trading.orders import (
    Order,
    OrderSide,
)


def make_market_result(
) -> MarketDataResult:

    data = pd.DataFrame(
        {
            "Open": [100.0],
            "High": [101.0],
            "Low": [99.0],
            "Close": [100.0],
            "Adj Close": [100.0],
            "Volume": [1_000_000],
        },
        index=pd.to_datetime(
            [
                "2026-09-08"
            ]
        ),
    )

    return MarketDataResult(
        ticker="AAPL",
        data=data,
        provider="test",
        retrieved_at_utc=datetime(
            2026,
            9,
            8,
            13,
            30,
            30,
            tzinfo=timezone.utc,
        ),
    )


def make_quality_report(
) -> DataQualityReport:

    return DataQualityReport(
        ticker="AAPL",
        checked_at_utc=datetime(
            2026,
            9,
            8,
            13,
            31,
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


def make_storage(
    tmp_path,
):

    db = tmp_path / "test.db"

    accounts = AccountStorage(db)
    trades = TradingStorage(db)
    market = MarketDataStorage(db)
    attempts = ExecutionAttemptStorage(db)

    accounts.initialize()
    trades.initialize()
    market.initialize()
    attempts.initialize()

    accounts.create_account(
        10_000
    )

    order = Order(
        order_id="order-1",
        ticker="AAPL",
        side=OrderSide.BUY,
        quantity=5,
        signal_timestamp_utc=datetime(
            2026,
            9,
            4,
            21,
            0,
            tzinfo=timezone.utc,
        ),
        execution_session=date(
            2026,
            9,
            8,
        ),
    )

    trades.save_order(
        order
    )

    snapshot = (
        market.save_market_snapshot(
            result=(
                make_market_result()
            ),
            quality_report=(
                make_quality_report()
            ),
        )
    )

    return (
        attempts,
        snapshot.run_id,
    )


def test_started_attempt_is_persisted(
    tmp_path,
):

    attempts, run_id = (
        make_storage(
            tmp_path
        )
    )

    record = attempts.start_attempt(
        order_id="order-1",
        execution_run_id=run_id,
        execution_observed_at_utc=datetime(
            2026,
            9,
            8,
            13,
            31,
            tzinfo=timezone.utc,
        ),
        attempt_id="attempt-1",
    )

    assert (
        record.outcome
        == ExecutionAttemptOutcome.STARTED
    )

    assert (
        record.execution_run_id
        == run_id
    )

    assert (
        attempts.count_attempts()
        == 1
    )


def test_attempt_can_be_marked_filled(
    tmp_path,
):

    attempts, run_id = (
        make_storage(
            tmp_path
        )
    )

    attempts.start_attempt(
        order_id="order-1",
        execution_run_id=run_id,
        execution_observed_at_utc=datetime(
            2026,
            9,
            8,
            13,
            31,
            tzinfo=timezone.utc,
        ),
        attempt_id="attempt-1",
    )

    record = attempts.finalize_attempt(
        attempt_id="attempt-1",
        outcome=(
            ExecutionAttemptOutcome.FILLED
        ),
    )

    assert (
        record.outcome
        == ExecutionAttemptOutcome.FILLED
    )

    assert (
        record.completed_at_utc
        is not None
    )


def test_attempt_can_be_marked_rejected(
    tmp_path,
):

    attempts, run_id = (
        make_storage(
            tmp_path
        )
    )

    attempts.start_attempt(
        order_id="order-1",
        execution_run_id=run_id,
        execution_observed_at_utc=datetime(
            2026,
            9,
            8,
            13,
            31,
            tzinfo=timezone.utc,
        ),
        attempt_id="attempt-1",
    )

    record = attempts.finalize_attempt(
        attempt_id="attempt-1",
        outcome=(
            ExecutionAttemptOutcome.REJECTED
        ),
        error_type=(
            "ExecutionRiskRejectedError"
        ),
        error_message=(
            "Position limit exceeded."
        ),
    )

    assert (
        record.outcome
        == ExecutionAttemptOutcome.REJECTED
    )

    assert (
        record.error_type
        == "ExecutionRiskRejectedError"
    )


def test_attempt_can_be_marked_failed(
    tmp_path,
):

    attempts, run_id = (
        make_storage(
            tmp_path
        )
    )

    attempts.start_attempt(
        order_id="order-1",
        execution_run_id=run_id,
        execution_observed_at_utc=datetime(
            2026,
            9,
            8,
            13,
            31,
            tzinfo=timezone.utc,
        ),
        attempt_id="attempt-1",
    )

    record = attempts.finalize_attempt(
        attempt_id="attempt-1",
        outcome=(
            ExecutionAttemptOutcome.FAILED
        ),
        error_type="RuntimeError",
        error_message="Test failure.",
    )

    assert (
        record.outcome
        == ExecutionAttemptOutcome.FAILED
    )


def test_duplicate_order_snapshot_attempt_is_blocked(
    tmp_path,
):

    attempts, run_id = (
        make_storage(
            tmp_path
        )
    )

    attempts.start_attempt(
        order_id="order-1",
        execution_run_id=run_id,
        execution_observed_at_utc=datetime(
            2026,
            9,
            8,
            13,
            31,
            tzinfo=timezone.utc,
        ),
    )

    with pytest.raises(
        DuplicateExecutionAttemptError
    ):
        attempts.start_attempt(
            order_id="order-1",
            execution_run_id=run_id,
            execution_observed_at_utc=datetime(
                2026,
                9,
                8,
                13,
                31,
                5,
                tzinfo=timezone.utc,
            ),
        )


def test_terminal_attempt_cannot_be_rewritten(
    tmp_path,
):

    attempts, run_id = (
        make_storage(
            tmp_path
        )
    )

    attempts.start_attempt(
        order_id="order-1",
        execution_run_id=run_id,
        execution_observed_at_utc=datetime(
            2026,
            9,
            8,
            13,
            31,
            tzinfo=timezone.utc,
        ),
        attempt_id="attempt-1",
    )

    attempts.finalize_attempt(
        attempt_id="attempt-1",
        outcome=(
            ExecutionAttemptOutcome.REJECTED
        ),
    )

    with pytest.raises(
        InvalidExecutionAttemptStateError
    ):
        attempts.finalize_attempt(
            attempt_id="attempt-1",
            outcome=(
                ExecutionAttemptOutcome.FILLED
            ),
        )