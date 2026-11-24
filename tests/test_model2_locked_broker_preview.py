
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from database.account_storage import AccountStorage
from database.execution_attempt_storage import (
    ExecutionAttemptStorage,
)
from database.storage import MarketDataStorage
from database.trading_storage import TradingStorage
from model2_config import MODEL_2_VERSION
from model2_execution_provenance import (
    record_model2_execution_observation,
)
from model2_locked_broker_preview import (
    Model2LockedBrokerPreviewError,
    preview_locked_model2_broker,
)
from services.intraday_collector import (
    IntradayObservation,
    IntradayObservationStorage,
)
from trading.flexible_execution_observation import (
    FlexibleExecutionObservationValidator,
)
from trading.orders import Order, OrderSide


SESSION = date(2026, 9, 18)

NOW = datetime(
    2026, 9, 18, 13, 46, 10,
    tzinfo=timezone.utc,
)


def setup_databases(tmp_path, monkeypatch):
    source_db = tmp_path / "source.db"
    trading_db = tmp_path / "trading.db"

    monkeypatch.setenv(
        "TRADING_AGENT_DB_PATH",
        str(source_db),
    )
    monkeypatch.setenv(
        "PAPER_TRADING_MODEL2_DB_PATH",
        str(trading_db),
    )

    observations = IntradayObservationStorage(
        source_db
    )
    observations.initialize()

    MarketDataStorage(trading_db).initialize()

    storage = TradingStorage(trading_db)
    storage.initialize()

    accounts = AccountStorage(trading_db)
    accounts.initialize()
    accounts.create_account(
        starting_cash=10000,
        account_id="model2-paper",
    )

    ExecutionAttemptStorage(trading_db).initialize()

    source = IntradayObservation(
        ticker="AAPL",
        provider="controlled-test",
        bar_start_utc=datetime(
            2026, 9, 18, 13, 45,
            tzinfo=timezone.utc,
        ),
        retrieved_at_utc=datetime(
            2026, 9, 18, 13, 46, 5,
            tzinfo=timezone.utc,
        ),
        open=100.0,
        high=102.0,
        low=99.0,
        close=101.0,
        volume=1000.0,
    )

    assert observations.save(source)

    observation = (
        FlexibleExecutionObservationValidator()
        .validate(
            observation=source,
            execution_session=SESSION,
            checked_at=NOW,
            expected_ticker="AAPL",
        )
    )

    provenance = record_model2_execution_observation(
        observation,
        now=NOW,
    )

    order = Order(
        order_id="broker-preview-AAPL",
        ticker="AAPL",
        side=OrderSide.BUY,
        quantity=2,
        signal_timestamp_utc=datetime(
            2026, 9, 17, 20, 45,
            tzinfo=timezone.utc,
        ),
        execution_session=SESSION,
    )

    storage.save_order(
        order,
        model_version=MODEL_2_VERSION,
    )

    # The configured observation DB remains source_db,
    # but the protected live Model 2 path is now
    # different from our temporary trading_db.
    monkeypatch.setenv(
        "PAPER_TRADING_MODEL2_DB_PATH",
        str(tmp_path / "protected-live-model2.db"),
    )

    return (
        trading_db,
        storage,
        order.order_id,
        observation,
        provenance.execution_run_id,
    )


def preview(db, order_id, observation):
    return preview_locked_model2_broker(
        database_path=db,
        order_id=order_id,
        execution_observation=observation,
        holding_observations={},
        clock=lambda: NOW,
    )


def test_broker_creates_in_memory_fill_with_slippage(
    tmp_path,
    monkeypatch,
):
    db, storage, order_id, observation, run_id = (
        setup_databases(tmp_path, monkeypatch)
    )

    result = preview(
        db,
        order_id,
        observation,
    )

    assert result.execution_run_id == run_id
    assert result.fill.order_id == order_id
    assert result.fill.reference_price == Decimal("101.00")
    assert result.fill.fill_price == Decimal("101.05")
    assert result.fill.quantity == 2
    assert result.cash_before == Decimal("10000.00")
    assert result.cash_after == Decimal("9797.90")

    # A broker preview must not persist its fill.
    assert storage.count_fills() == 0
    assert storage.get_order_status(order_id) == "PENDING"


def test_preview_does_not_write_execution_attempt(
    tmp_path,
    monkeypatch,
):
    db, storage, order_id, observation, _ = (
        setup_databases(tmp_path, monkeypatch)
    )

    preview(db, order_id, observation)

    with sqlite3.connect(db) as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM execution_attempts"
        ).fetchone()[0]

    assert count == 0
    assert storage.count_fills() == 0


def test_expired_order_is_blocked_before_broker(
    tmp_path,
    monkeypatch,
):
    db, storage, order_id, observation, _ = (
        setup_databases(tmp_path, monkeypatch)
    )

    storage.reject_order(
        order_id=order_id,
        rejection_code="EXECUTION_WINDOW_EXPIRED",
        rejection_reason="Controlled test expiry.",
    )

    with pytest.raises(
        Model2LockedBrokerPreviewError,
        match="not PENDING",
    ):
        preview(db, order_id, observation)

    assert storage.count_fills() == 0