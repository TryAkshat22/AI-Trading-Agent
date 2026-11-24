
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
from model2_execution_provenance import (
    record_model2_execution_observation,
)
from model2_integrated_executor import (
    Model2IntegratedExecutionError,
    execute_test_model2_order,
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

START = datetime(
    2026, 9, 18, 13, 46, 10,
    tzinfo=timezone.utc,
)

END = datetime(
    2026, 9, 18, 13, 46, 11,
    tzinfo=timezone.utc,
)

TOO_LATE = datetime(
    2026, 9, 18, 19, 30,
    tzinfo=timezone.utc,
)


def clock_sequence(*values):
    iterator = iter(values)
    return lambda: next(iterator)


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

    ExecutionAttemptStorage(
        trading_db
    ).initialize()

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
            checked_at=START,
            expected_ticker="AAPL",
        )
    )

    provenance = record_model2_execution_observation(
        observation,
        now=START,
    )

    order = Order(
        order_id="integrated-test-AAPL",
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

    # The temporary trading DB is now separate
    # from the configured protected live path.
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


def execute(
    db,
    order_id,
    observation,
    *,
    clock=None,
    after_fill_insert=None,
):
    return execute_test_model2_order(
        database_path=db,
        order_id=order_id,
        execution_observation=observation,
        holding_observations={},
        clock=(
            clock
            if clock is not None
            else clock_sequence(START, END)
        ),
        after_fill_insert=after_fill_insert,
    )


def test_integrated_execution_commits_everything(
    tmp_path,
    monkeypatch,
):
    db, storage, order_id, observation, run_id = (
        setup_databases(tmp_path, monkeypatch)
    )

    result = execute(
        db,
        order_id,
        observation,
    )

    assert result.execution_run_id == run_id
    assert result.reference_price == "101.00"
    assert result.fill_price == "101.05"

    assert storage.get_order_status(order_id) == "FILLED"
    assert storage.count_fills() == 1

    with sqlite3.connect(db) as connection:
        attempts = connection.execute(
            """
            SELECT outcome, execution_run_id
            FROM execution_attempts
            WHERE order_id = ?
            """,
            (order_id,),
        ).fetchall()

        lineage = connection.execute(
            """
            SELECT execution_run_id
            FROM fill_execution_lineage
            WHERE fill_id = ?
            """,
            (result.fill_id,),
        ).fetchone()

    assert attempts == [("FILLED", run_id)]
    assert lineage == (run_id,)


def test_failure_after_fill_insert_rolls_back_all_records(
    tmp_path,
    monkeypatch,
):
    db, storage, order_id, observation, _ = (
        setup_databases(tmp_path, monkeypatch)
    )

    def injected_failure():
        raise RuntimeError("Injected failure")

    with pytest.raises(
        RuntimeError,
        match="Injected failure",
    ):
        execute(
            db,
            order_id,
            observation,
            clock=clock_sequence(START),
            after_fill_insert=injected_failure,
        )

    assert storage.get_order_status(order_id) == "PENDING"
    assert storage.count_fills() == 0

    with sqlite3.connect(db) as connection:
        attempts = connection.execute(
            "SELECT COUNT(*) FROM execution_attempts"
        ).fetchone()[0]

        lineage = connection.execute(
            "SELECT COUNT(*) FROM fill_execution_lineage"
        ).fetchone()[0]

    assert attempts == 0
    assert lineage == 0


def test_expired_order_cannot_execute(
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
        Model2IntegratedExecutionError,
        match="not PENDING",
    ):
        execute(
            db,
            order_id,
            observation,
            clock=clock_sequence(START),
        )

    assert storage.count_fills() == 0


def test_window_closing_before_commit_rolls_back(
    tmp_path,
    monkeypatch,
):
    db, storage, order_id, observation, _ = (
        setup_databases(tmp_path, monkeypatch)
    )

    with pytest.raises(
        Exception,
        match="Outside the Model 2 execution window",
    ):
        execute(
            db,
            order_id,
            observation,
            clock=clock_sequence(START, TOO_LATE),
        )

    assert storage.get_order_status(order_id) == "PENDING"
    assert storage.count_fills() == 0

    with sqlite3.connect(db) as connection:
        attempts = connection.execute(
            "SELECT COUNT(*) FROM execution_attempts"
        ).fetchone()[0]

    assert attempts == 0


def test_competing_integrated_attempts_fill_once(
    tmp_path,
    monkeypatch,
):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    db, storage, order_id, observation, _ = (
        setup_databases(tmp_path, monkeypatch)
    )

    barrier = Barrier(2)

    def worker():
        barrier.wait(timeout=10)

        try:
            result = execute(
                db,
                order_id,
                observation,
                clock=clock_sequence(START, END),
            )
            return ("FILLED", result.fill_id)
        except Model2IntegratedExecutionError as exc:
            return ("BLOCKED", str(exc))

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(worker)
            for _ in range(2)
        ]

        results = [
            future.result(timeout=30)
            for future in futures
        ]

    assert sorted(
        outcome
        for outcome, _ in results
    ) == ["BLOCKED", "FILLED"]

    assert storage.get_order_status(order_id) == "FILLED"
    assert storage.count_fills() == 1

    with sqlite3.connect(db) as connection:
        attempts = connection.execute(
            """
            SELECT outcome
            FROM execution_attempts
            WHERE order_id = ?
            """,
            (order_id,),
        ).fetchall()

        lineage_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM fill_execution_lineage
            """,
        ).fetchone()[0]

    assert attempts == [("FILLED",)]
    assert lineage_count == 1


def test_existing_holding_uses_verified_valuation(
    tmp_path,
    monkeypatch,
):
    from decimal import Decimal

    from model2_locked_portfolio import (
        locked_test_model2_portfolio,
    )

    db, storage, order_id, execution_observation, _ = (
        setup_databases(tmp_path, monkeypatch)
    )

    # Add one previously filled MSFT position to
    # this TEMPORARY trading database.
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

    from trading.orders import Fill, OrderStatus

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

    # Record a genuine, controlled MSFT observation
    # in the TEMPORARY source database.
    from model2_config import get_model2_paths

    source_db = get_model2_paths().observation_database

    msft_source = IntradayObservation(
        ticker="MSFT",
        provider="controlled-test",
        bar_start_utc=datetime(
            2026, 9, 18, 13, 45,
            tzinfo=timezone.utc,
        ),
        retrieved_at_utc=datetime(
            2026, 9, 18, 13, 46, 5,
            tzinfo=timezone.utc,
        ),
        open=99.0,
        high=101.0,
        low=98.0,
        close=100.0,
        volume=1000.0,
    )

    source_storage = IntradayObservationStorage(
        source_db
    )

    assert source_storage.save(msft_source)

    msft_observation = (
        FlexibleExecutionObservationValidator()
        .validate(
            observation=msft_source,
            execution_session=SESSION,
            checked_at=START,
            expected_ticker="MSFT",
        )
    )

    # Temporarily identify trading.db as Model 2
    # ONLY while recording its test provenance.
    monkeypatch.setenv(
        "PAPER_TRADING_MODEL2_DB_PATH",
        str(db),
    )

    record_model2_execution_observation(
        msft_observation,
        now=START,
    )

    # Restore the protected path BEFORE invoking
    # the test-only integrated executor.
    monkeypatch.setenv(
        "PAPER_TRADING_MODEL2_DB_PATH",
        str(tmp_path / "protected-live-model2.db"),
    )

    result = execute_test_model2_order(
        database_path=db,
        order_id=order_id,
        execution_observation=execution_observation,
        holding_observations={
            "MSFT": msft_observation,
        },
        clock=clock_sequence(START, END),
    )

    assert result.order_id == order_id
    assert storage.get_order_status(order_id) == "FILLED"
    assert storage.count_fills() == 2

    # The second trade must use cash remaining
    # after the first trade, not the original $10,000.
    with locked_test_model2_portfolio(db) as (
        _connection,
        portfolio,
    ):
        assert portfolio.cash == Decimal("9697.85")
        assert portfolio.positions["MSFT"].quantity == 1
        assert portfolio.positions["AAPL"].quantity == 2


def test_missing_holding_observation_prevents_fill(
    tmp_path,
    monkeypatch,
):
    from decimal import Decimal

    from trading.orders import Fill, OrderStatus

    db, storage, order_id, execution_observation, _ = (
        setup_databases(tmp_path, monkeypatch)
    )

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

    with pytest.raises(
        Model2IntegratedExecutionError,
        match="Holding observations do not match",
    ):
        execute_test_model2_order(
            database_path=db,
            order_id=order_id,
            execution_observation=execution_observation,
            holding_observations={},
            clock=clock_sequence(START),
        )

    assert storage.get_order_status(order_id) == "PENDING"
    assert storage.count_fills() == 1

    with sqlite3.connect(db) as connection:
        attempts = connection.execute(
            """
            SELECT COUNT(*)
            FROM execution_attempts
            WHERE order_id = ?
            """,
            (order_id,),
        ).fetchone()[0]

    assert attempts == 0