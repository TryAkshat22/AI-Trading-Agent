
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from database.account_storage import AccountStorage
from database.storage import MarketDataStorage
from database.trading_storage import TradingStorage
from model2_config import MODEL_2_VERSION
from model2_locked_execution_preview import (
    Model2LockedPreviewError,
    preview_locked_model2_execution,
)
from risk.risk_engine import RiskDecision
from trading.flexible_execution_observation import (
    FlexibleExecutionObservation,
)
from trading.orders import (
    Fill,
    Order,
    OrderSide,
    OrderStatus,
)


SESSION = date(2026, 9, 18)

NOW = datetime(
    2026, 9, 18, 13, 46, 10,
    tzinfo=timezone.utc,
)


def observation(ticker: str, price: float):
    start = datetime(
        2026, 9, 18, 13, 45,
        tzinfo=timezone.utc,
    )

    return FlexibleExecutionObservation(
        ticker=ticker,
        execution_session=SESSION,
        reference_price=price,
        price_field="Close",
        provider="controlled-test",
        bar_start_utc=start,
        bar_end_utc=start + timedelta(minutes=1),
        retrieved_at_utc=datetime(
            2026, 9, 18, 13, 46, 5,
            tzinfo=timezone.utc,
        ),
        execution_checked_at_utc=NOW,
        model="flexible-observed-close-v1",
    )


def setup_database(
    tmp_path,
    monkeypatch,
    *,
    existing_holding=False,
):
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

    storage = TradingStorage(db)
    storage.initialize()

    accounts = AccountStorage(db)
    accounts.initialize()
    accounts.create_account(
        starting_cash=10000,
        account_id="model2-paper",
    )

    if existing_holding:
        held_order = Order(
            order_id="previous-MSFT",
            ticker="MSFT",
            side=OrderSide.BUY,
            quantity=1,
            signal_timestamp_utc=datetime(
                2026, 9, 17, 20, 45,
                tzinfo=timezone.utc,
            ),
            execution_session=SESSION,
        )

        storage.save_order(
            held_order,
            model_version=MODEL_2_VERSION,
        )

        storage.save_fill(
            Fill(
                order_id=held_order.order_id,
                ticker="MSFT",
                side=OrderSide.BUY,
                quantity=1,
                reference_price=Decimal("100.00"),
                fill_price=Decimal("100.05"),
                gross_value=Decimal("100.05"),
                fees=Decimal("0.00"),
                slippage_cost=Decimal("0.05"),
                execution_session=SESSION,
                status=OrderStatus.FILLED,
                realized_pnl=Decimal("0.00"),
            )
        )

    order = Order(
        order_id="preview-AAPL",
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

    return db, storage, order.order_id


def preview(
    db,
    order_id,
    *,
    holdings=None,
):
    return preview_locked_model2_execution(
        database_path=db,
        order_id=order_id,
        execution_observation=observation(
            "AAPL",
            101.0,
        ),
        holding_observations=(
            holdings
            if holdings is not None
            else {}
        ),
        clock=lambda: NOW,
    )


def test_empty_portfolio_risk_is_assessed_under_lock(
    tmp_path,
    monkeypatch,
):
    db, storage, order_id = setup_database(
        tmp_path,
        monkeypatch,
    )

    result = preview(db, order_id)

    assert (
        result.risk.assessment.decision
        == RiskDecision.APPROVE
    )
    assert result.starting_cash == Decimal("10000.00")
    assert result.existing_positions == ()

    assert storage.get_order_status(order_id) == "PENDING"
    assert storage.count_fills() == 0


def test_existing_holding_uses_rebuilt_cash_and_price(
    tmp_path,
    monkeypatch,
):
    db, storage, order_id = setup_database(
        tmp_path,
        monkeypatch,
        existing_holding=True,
    )

    result = preview(
        db,
        order_id,
        holdings={
            "MSFT": observation("MSFT", 100.0)
        },
    )

    assert (
        result.starting_cash
        == Decimal("9899.95")
    )
    assert result.existing_positions == ("MSFT",)
    assert (
        result.risk.assessment.decision
        == RiskDecision.APPROVE
    )
    assert storage.count_fills() == 1
    assert storage.get_order_status(order_id) == "PENDING"


def test_missing_holding_price_blocks_preview(
    tmp_path,
    monkeypatch,
):
    db, storage, order_id = setup_database(
        tmp_path,
        monkeypatch,
        existing_holding=True,
    )

    with pytest.raises(
        Model2LockedPreviewError,
        match="Missing valuation observations",
    ):
        preview(db, order_id)

    assert storage.count_fills() == 1
    assert storage.get_order_status(order_id) == "PENDING"


def test_expired_order_is_blocked(
    tmp_path,
    monkeypatch,
):
    db, storage, order_id = setup_database(
        tmp_path,
        monkeypatch,
    )

    storage.reject_order(
        order_id=order_id,
        rejection_code="EXECUTION_WINDOW_EXPIRED",
        rejection_reason="Controlled test expiry.",
    )

    with pytest.raises(
        Model2LockedPreviewError,
        match="not PENDING",
    ):
        preview(db, order_id)

    assert storage.count_fills() == 0


def test_preview_never_creates_fill_or_attempt(
    tmp_path,
    monkeypatch,
):
    db, storage, order_id = setup_database(
        tmp_path,
        monkeypatch,
    )

    preview(db, order_id)

    with sqlite3.connect(db) as connection:
        attempts_table = connection.execute(
            """
            SELECT 1 FROM sqlite_master
            WHERE type = 'table'
              AND name = 'execution_attempts'
            """
        ).fetchone()

        attempts = (
            connection.execute(
                "SELECT COUNT(*) FROM execution_attempts"
            ).fetchone()[0]
            if attempts_table is not None
            else 0
        )

    assert attempts == 0
    assert storage.count_fills() == 0
    assert storage.get_order_status(order_id) == "PENDING"