
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from database.account_storage import AccountStorage
from database.storage import MarketDataStorage
from database.trading_storage import TradingStorage
from model2_config import MODEL_2_VERSION
from model2_locked_portfolio import (
    Model2LockedPortfolioError,
    locked_test_model2_portfolio,
)
from trading.orders import (
    Fill,
    Order,
    OrderSide,
    OrderStatus,
)


SESSION = date(2026, 9, 18)


def setup_database(tmp_path, monkeypatch):
    db = tmp_path / "temporary-model2.db"

    monkeypatch.setenv(
        "TRADING_AGENT_DB_PATH",
        str(tmp_path / "protected-model1.db"),
    )

    monkeypatch.setenv(
        "PAPER_TRADING_MODEL2_DB_PATH",
        str(tmp_path / "protected-model2.db"),
    )

    MarketDataStorage(db).initialize()
    TradingStorage(db).initialize()

    accounts = AccountStorage(db)
    accounts.initialize()
    accounts.create_account(
        starting_cash=10000,
        account_id="model2-paper",
    )

    return db


def insert_filled_order(db):
    order = Order(
        order_id="locked-test-AAPL",
        ticker="AAPL",
        side=OrderSide.BUY,
        quantity=2,
        signal_timestamp_utc=datetime(
            2026, 9, 17, 20, 45,
            tzinfo=timezone.utc,
        ),
        execution_session=SESSION,
    )

    storage = TradingStorage(db)

    storage.save_order(
        order,
        model_version=MODEL_2_VERSION,
    )

    fill = Fill(
        order_id=order.order_id,
        ticker="AAPL",
        side=OrderSide.BUY,
        quantity=2,
        reference_price=Decimal("100.00"),
        fill_price=Decimal("100.05"),
        gross_value=Decimal("200.10"),
        fees=Decimal("0.00"),
        slippage_cost=Decimal("0.10"),
        execution_session=SESSION,
        status=OrderStatus.FILLED,
        realized_pnl=Decimal("0.00"),
    )

    storage.save_fill(fill)

    return order.order_id


def test_empty_account_rebuilds_under_lock(
    tmp_path,
    monkeypatch,
):
    db = setup_database(tmp_path, monkeypatch)

    with locked_test_model2_portfolio(db) as (
        connection,
        portfolio,
    ):
        assert connection.in_transaction
        assert portfolio.cash == Decimal("10000.00")
        assert portfolio.positions == {}

    assert TradingStorage(db).count_fills() == 0


def test_existing_fill_is_replayed_under_lock(
    tmp_path,
    monkeypatch,
):
    db = setup_database(tmp_path, monkeypatch)
    insert_filled_order(db)

    with locked_test_model2_portfolio(db) as (
        connection,
        portfolio,
    ):
        assert connection.in_transaction
        assert portfolio.cash == Decimal("9799.90")
        assert portfolio.positions["AAPL"].quantity == 2
        assert (
            portfolio.positions["AAPL"].average_cost
            == Decimal("100.05")
        )

    assert TradingStorage(db).count_fills() == 1


def test_inconsistent_fill_is_blocked(
    tmp_path,
    monkeypatch,
):
    db = setup_database(tmp_path, monkeypatch)
    order_id = insert_filled_order(db)

    # Deliberate corruption in a TEMPORARY database.
    with sqlite3.connect(db) as connection:
        connection.execute(
            """
            UPDATE paper_orders
            SET status = 'PENDING'
            WHERE order_id = ?
            """,
            (order_id,),
        )

    with pytest.raises(
        Model2LockedPortfolioError,
        match="inconsistent",
    ):
        with locked_test_model2_portfolio(db):
            pass