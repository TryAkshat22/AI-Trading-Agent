
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timezone

import pytest

from database.account_storage import AccountStorage
from database.execution_attempt_storage import (
    ExecutionAttemptStorage,
)
from database.storage import MarketDataStorage
from database.trading_storage import TradingStorage
from model2_config import MODEL_2_VERSION
from model2_execution_preflight import (
    Model2PreflightError,
    inspect_execution_prerequisites,
)
from trading.orders import Order, OrderSide


SESSION = date(2026, 9, 21)

NOW = datetime(
    2026, 9, 21, 13, 50,
    tzinfo=timezone.utc,
)


def setup_databases(
    tmp_path,
    monkeypatch,
    *,
    attempts_table=True,
):
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

    source_db.touch()

    MarketDataStorage(trading_db).initialize()
    storage = TradingStorage(trading_db)
    storage.initialize()

    accounts = AccountStorage(trading_db)
    accounts.initialize()
    accounts.create_account(
        starting_cash=10000,
        account_id="model2-paper",
    )

    if attempts_table:
        ExecutionAttemptStorage(
            trading_db
        ).initialize()

    # Create the provenance table in this TEMP database
    # because preflight requires its schema to exist.
    with sqlite3.connect(trading_db) as connection:
        connection.execute(
            """
            CREATE TABLE
            model2_execution_observation_lineage (
                execution_run_id TEXT PRIMARY KEY
            )
            """
        )

    order = Order(
        order_id="preflight-test-AAPL",
        ticker="AAPL",
        side=OrderSide.BUY,
        quantity=2,
        signal_timestamp_utc=datetime(
            2026, 9, 18, 20, 45,
            tzinfo=timezone.utc,
        ),
        execution_session=SESSION,
    )

    storage.save_order(
        order,
        model_version=MODEL_2_VERSION,
    )

    return trading_db, storage, order.order_id


def test_valid_pending_order_passes_read_only_preflight(
    tmp_path,
    monkeypatch,
):
    db, storage, order_id = setup_databases(
        tmp_path,
        monkeypatch,
    )

    result = inspect_execution_prerequisites(
        execution_session=SESSION,
        now=NOW,
    )

    assert result == (order_id,)
    assert storage.get_order_status(order_id) == "PENDING"
    assert storage.count_fills() == 0


def test_missing_attempts_table_blocks_preflight(
    tmp_path,
    monkeypatch,
):
    db, storage, order_id = setup_databases(
        tmp_path,
        monkeypatch,
        attempts_table=False,
    )

    with pytest.raises(
        Model2PreflightError,
        match="execution_attempts",
    ):
        inspect_execution_prerequisites(
            execution_session=SESSION,
            now=NOW,
        )

    with sqlite3.connect(db) as connection:
        found = connection.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table'
              AND name = 'execution_attempts'
            """
        ).fetchone()

    assert found is None
    assert storage.get_order_status(order_id) == "PENDING"


def test_expired_order_is_blocked(
    tmp_path,
    monkeypatch,
):
    _, storage, order_id = setup_databases(
        tmp_path,
        monkeypatch,
    )

    storage.reject_order(
        order_id=order_id,
        rejection_code="EXECUTION_WINDOW_EXPIRED",
        rejection_reason="Controlled test expiry.",
    )

    with pytest.raises(
        Model2PreflightError,
        match="not PENDING",
    ):
        inspect_execution_prerequisites(
            execution_session=SESSION,
            now=NOW,
        )


def test_wrong_execution_day_is_blocked(
    tmp_path,
    monkeypatch,
):
    setup_databases(tmp_path, monkeypatch)

    with pytest.raises(
        Exception,
        match="today's New York calendar date",
    ):
        inspect_execution_prerequisites(
            execution_session=date(2026, 9, 18),
            now=NOW,
        )