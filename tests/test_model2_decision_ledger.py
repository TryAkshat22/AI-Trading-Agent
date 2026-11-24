
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from database.account_storage import AccountStorage
from database.trading_storage import TradingStorage
from model2_config import MODEL_2_ACCOUNT_ID
from model2_decision_ledger import (
    Model2DecisionAlreadyClaimedError,
    Model2DecisionLedger,
    Model2DecisionLedgerError,
)


SESSION = date(2026, 9, 16)

START = datetime(
    2026, 9, 16, 21, 0,
    tzinfo=timezone.utc,
)

END = START + timedelta(minutes=2)


def setup_ledger(tmp_path, monkeypatch):
    model1 = tmp_path / "model1.db"
    model2 = tmp_path / "model2.db"

    monkeypatch.setenv(
        "TRADING_AGENT_DB_PATH",
        str(model1),
    )
    monkeypatch.setenv(
        "PAPER_TRADING_MODEL2_DB_PATH",
        str(model2),
    )

    accounts = AccountStorage(model2)
    trading = TradingStorage(model2)

    accounts.initialize()
    trading.initialize()

    accounts.create_account(
        starting_cash=10000,
        account_id=MODEL_2_ACCOUNT_ID,
    )

    ledger = Model2DecisionLedger()
    ledger.initialize()

    return model1, model2, ledger


def test_initialization_does_not_create_orders_or_model1(
    tmp_path,
    monkeypatch,
):
    model1, model2, ledger = setup_ledger(
        tmp_path, monkeypatch
    )

    trading = TradingStorage(model2)

    assert ledger.get_for_session(SESSION) is None
    assert trading.count_orders() == 0
    assert trading.count_fills() == 0
    assert not model1.exists()


def test_claim_persists_started_run(
    tmp_path,
    monkeypatch,
):
    _, _, ledger = setup_ledger(
        tmp_path, monkeypatch
    )

    record = ledger.claim(SESSION, START)

    assert record.status == "STARTED"
    assert record.decision_session == SESSION
    assert record.orders_created is None

    saved = ledger.get_for_session(SESSION)

    assert saved is not None
    assert saved.run_id == record.run_id


def test_second_claim_is_blocked_even_without_orders(
    tmp_path,
    monkeypatch,
):
    _, _, ledger = setup_ledger(
        tmp_path, monkeypatch
    )

    ledger.claim(SESSION, START)

    with pytest.raises(
        Model2DecisionAlreadyClaimedError
    ):
        ledger.claim(SESSION, START)


def test_zero_order_completed_run_blocks_retry(
    tmp_path,
    monkeypatch,
):
    _, _, ledger = setup_ledger(
        tmp_path, monkeypatch
    )

    started = ledger.claim(SESSION, START)

    finished = ledger.finish(
        started.run_id,
        status="COMPLETED",
        finished_at=END,
        orders_created=0,
        failed_tickers=0,
    )

    assert finished.status == "COMPLETED"
    assert finished.orders_created == 0

    with pytest.raises(
        Model2DecisionAlreadyClaimedError
    ):
        ledger.claim(SESSION, END)


def test_failed_run_blocks_automatic_retry(
    tmp_path,
    monkeypatch,
):
    _, _, ledger = setup_ledger(
        tmp_path, monkeypatch
    )

    started = ledger.claim(SESSION, START)

    finished = ledger.finish(
        started.run_id,
        status="FAILED",
        finished_at=END,
        orders_created=1,
        failed_tickers=1,
        error_message="Controlled failure.",
    )

    assert finished.status == "FAILED"
    assert finished.orders_created == 1
    assert finished.failed_tickers == 1

    with pytest.raises(
        Model2DecisionAlreadyClaimedError
    ):
        ledger.claim(SESSION, END)


def test_run_cannot_be_finalized_twice(
    tmp_path,
    monkeypatch,
):
    _, _, ledger = setup_ledger(
        tmp_path, monkeypatch
    )

    started = ledger.claim(SESSION, START)

    ledger.finish(
        started.run_id,
        status="COMPLETED",
        finished_at=END,
        orders_created=0,
        failed_tickers=0,
    )

    with pytest.raises(
        Model2DecisionLedgerError
    ):
        ledger.finish(
            started.run_id,
            status="FAILED",
            finished_at=END,
            orders_created=0,
            failed_tickers=1,
        )


def test_missing_database_is_not_created(
    tmp_path,
    monkeypatch,
):
    model1 = tmp_path / "model1.db"
    model2 = tmp_path / "missing-model2.db"

    monkeypatch.setenv(
        "TRADING_AGENT_DB_PATH",
        str(model1),
    )
    monkeypatch.setenv(
        "PAPER_TRADING_MODEL2_DB_PATH",
        str(model2),
    )

    ledger = Model2DecisionLedger()

    with pytest.raises(
        Model2DecisionLedgerError
    ):
        ledger.initialize()

    assert not model1.exists()
    assert not model2.exists()


def test_model1_database_path_is_rejected(
    tmp_path,
    monkeypatch,
):
    model1 = tmp_path / "model1.db"
    model2 = tmp_path / "model2.db"

    monkeypatch.setenv(
        "TRADING_AGENT_DB_PATH",
        str(model1),
    )
    monkeypatch.setenv(
        "PAPER_TRADING_MODEL2_DB_PATH",
        str(model2),
    )

    with pytest.raises(
        Model2DecisionLedgerError
    ):
        Model2DecisionLedger(
            database_path=model1
        )