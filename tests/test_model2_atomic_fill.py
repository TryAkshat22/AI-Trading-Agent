
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from database.account_storage import AccountStorage
from database.execution_attempt_storage import ExecutionAttemptStorage
from database.storage import MarketDataStorage
from database.trading_storage import TradingStorage
from model2_atomic_fill import (
    Model2AtomicFillError,
    commit_model2_test_fill,
)
from model2_execution_provenance import (
    record_model2_execution_observation,
)
from model2_config import MODEL_2_VERSION
from services.intraday_collector import (
    IntradayObservation,
    IntradayObservationStorage,
)
from trading.flexible_execution_observation import (
    FlexibleExecutionObservationValidator,
)
from trading.orders import Fill, Order, OrderSide, OrderStatus


SESSION = date(2026, 9, 18)

START = datetime(
    2026, 9, 18, 13, 46, 10,
    tzinfo=timezone.utc,
)

END = datetime(
    2026, 9, 18, 13, 46, 11,
    tzinfo=timezone.utc,
)


def make_fixture(tmp_path, monkeypatch):
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

    observations = IntradayObservationStorage(source_db)
    observations.initialize()

    MarketDataStorage(trading_db).initialize()
    TradingStorage(trading_db).initialize()

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

    validated = (
        FlexibleExecutionObservationValidator()
        .validate(
            observation=source,
            execution_session=SESSION,
            checked_at=START,
            expected_ticker="AAPL",
        )
    )

    provenance = record_model2_execution_observation(
        validated,
        now=START,
    )

        # Provenance is now safely stored in the temporary
    # trading database. Protect that database from the
    # test-only fill function's live-path guard by
    # restoring a different configured Model 2 path.
    monkeypatch.setenv(
        "PAPER_TRADING_MODEL2_DB_PATH",
        str(tmp_path / "protected-model2.db"),
    )
        
    order = Order(
        order_id="atomic-test-AAPL",
        ticker="AAPL",
        side=OrderSide.BUY,
        quantity=2,
        signal_timestamp_utc=datetime(
            2026, 9, 17, 20, 45,
            tzinfo=timezone.utc,
        ),
        execution_session=SESSION,
    )

    TradingStorage(trading_db).save_order(
        order,
        model_version=MODEL_2_VERSION,
    )

    fill = Fill(
        order_id=order.order_id,
        ticker="AAPL",
        side=OrderSide.BUY,
        quantity=2,
        reference_price=Decimal("101.00"),
        fill_price=Decimal("101.05"),
        gross_value=Decimal("202.10"),
        fees=Decimal("0.00"),
        slippage_cost=Decimal("0.10"),
        execution_session=SESSION,
        status=OrderStatus.FILLED,
        realized_pnl=Decimal("0.00"),
    )

    return trading_db, fill, provenance.execution_run_id


def clock_sequence(*values):
    iterator = iter(values)
    return lambda: next(iterator)


def counts(database_path):
    with sqlite3.connect(database_path) as connection:
        return {
            table: connection.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0]
            for table in (
                "execution_attempts",
                "paper_fills",
                "fill_execution_lineage",
            )
        }


def test_atomic_fill_commits_all_records(
    tmp_path,
    monkeypatch,
):
    db, fill, run_id = make_fixture(
        tmp_path,
        monkeypatch,
    )

    result = commit_model2_test_fill(
        database_path=db,
        fill=fill,
        execution_run_id=run_id,
        clock=clock_sequence(START, END),
    )

    assert result.order_id == fill.order_id

    assert counts(db) == {
        "execution_attempts": 1,
        "paper_fills": 1,
        "fill_execution_lineage": 1,
    }

    with sqlite3.connect(db) as connection:
        status = connection.execute(
            """
            SELECT status FROM paper_orders
            WHERE order_id = ?
            """,
            (fill.order_id,),
        ).fetchone()[0]

        outcome = connection.execute(
            """
            SELECT outcome FROM execution_attempts
            WHERE order_id = ?
            """,
            (fill.order_id,),
        ).fetchone()[0]

    assert status == "FILLED"
    assert outcome == "FILLED"


def test_failure_after_fill_insert_rolls_back_everything(
    tmp_path,
    monkeypatch,
):
    db, fill, run_id = make_fixture(
        tmp_path,
        monkeypatch,
    )

    def fail_after_insert():
        raise RuntimeError("Injected failure")

    with pytest.raises(
        RuntimeError,
        match="Injected failure",
    ):
        commit_model2_test_fill(
            database_path=db,
            fill=fill,
            execution_run_id=run_id,
            clock=clock_sequence(START),
            after_fill_insert=fail_after_insert,
        )

    assert counts(db) == {
        "execution_attempts": 0,
        "paper_fills": 0,
        "fill_execution_lineage": 0,
    }

    assert (
        TradingStorage(db).get_order_status(
            fill.order_id
        )
        == "PENDING"
    )


def test_second_fill_is_blocked(
    tmp_path,
    monkeypatch,
):
    db, fill, run_id = make_fixture(
        tmp_path,
        monkeypatch,
    )

    commit_model2_test_fill(
        database_path=db,
        fill=fill,
        execution_run_id=run_id,
        clock=clock_sequence(START, END),
    )

    with pytest.raises(
        Model2AtomicFillError,
        match="not PENDING",
    ):
        commit_model2_test_fill(
            database_path=db,
            fill=fill,
            execution_run_id=run_id,
            clock=clock_sequence(START),
        )

    assert counts(db)["paper_fills"] == 1


def test_window_closes_before_commit_and_rolls_back(
    tmp_path,
    monkeypatch,
):
    db, fill, run_id = make_fixture(
        tmp_path,
        monkeypatch,
    )

    TOO_LATE = datetime(
    2026, 9, 18, 19, 30,
    tzinfo=timezone.utc,
    )

    with pytest.raises(
        Exception,
        match="Outside the Model 2 execution window",
    ):
        commit_model2_test_fill(
            database_path=db,
            fill=fill,
            execution_run_id=run_id,
            clock=clock_sequence(START, TOO_LATE),
        )

    assert counts(db) == {
        "execution_attempts": 0,
        "paper_fills": 0,
        "fill_execution_lineage": 0,
    }

    assert (
        TradingStorage(db).get_order_status(
            fill.order_id
        )
        == "PENDING"
    )


def test_configured_live_database_is_blocked(
    tmp_path,
    monkeypatch,
):
    db, fill, run_id = make_fixture(
        tmp_path,
        monkeypatch,
    )

    monkeypatch.setenv(
        "PAPER_TRADING_MODEL2_DB_PATH",
        str(db),
    )

    with pytest.raises(
        Model2AtomicFillError,
        match="test-only component",
    ):
        commit_model2_test_fill(
            database_path=db,
            fill=fill,
            execution_run_id=run_id,
            clock=clock_sequence(START, END),
        )


def test_competing_attempts_produce_exactly_one_fill(
    tmp_path,
    monkeypatch,
):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    db, fill, run_id = make_fixture(
        tmp_path,
        monkeypatch,
    )

    start_together = Barrier(2)

    def attempt_fill():
        start_together.wait(timeout=10)

        try:
            result = commit_model2_test_fill(
                database_path=db,
                fill=fill,
                execution_run_id=run_id,
                clock=clock_sequence(START, END),
            )
            return ("FILLED", result.fill_id)

        except Model2AtomicFillError as exc:
            return ("BLOCKED", str(exc))

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(attempt_fill)
        second = pool.submit(attempt_fill)

        results = (
            first.result(timeout=30),
            second.result(timeout=30),
        )

    outcomes = sorted(
        outcome
        for outcome, _ in results
    )

    assert outcomes == ["BLOCKED", "FILLED"]

    assert counts(db) == {
        "execution_attempts": 1,
        "paper_fills": 1,
        "fill_execution_lineage": 1,
    }

    assert (
        TradingStorage(db).get_order_status(
            fill.order_id
        )
        == "FILLED"
    )

    with sqlite3.connect(db) as connection:
        attempt_outcome = connection.execute(
            """
            SELECT outcome
            FROM execution_attempts
            WHERE order_id = ?
            """,
            (fill.order_id,),
        ).fetchone()[0]

    assert attempt_outcome == "FILLED"