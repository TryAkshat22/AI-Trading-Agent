
from decimal import Decimal

import pytest

from database.account_storage import AccountStorage
from database.trading_storage import TradingStorage
from model2_config import MODEL_2_ACCOUNT_ID, MODEL_2_VERSION
from model2_decision_context import (
    Model2DecisionContextError,
    build_model2_decision_context,
)


def configure_paths(tmp_path, monkeypatch):
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

    return model1, model2


def create_model2_account(
    database_path,
    account_id=MODEL_2_ACCOUNT_ID,
    starting_cash=10000,
):
    accounts = AccountStorage(database_path)
    trading = TradingStorage(database_path)

    accounts.initialize()
    trading.initialize()

    accounts.create_account(
        starting_cash=starting_cash,
        account_id=account_id,
    )


def test_context_uses_model2_account_and_database(
    tmp_path,
    monkeypatch,
):
    model1, model2 = configure_paths(
        tmp_path, monkeypatch
    )
    create_model2_account(model2)

    context = build_model2_decision_context()

    assert context.database_path == model2.resolve()
    assert context.observation_database_path == model1.resolve()
    assert context.account_id == MODEL_2_ACCOUNT_ID
    assert context.model_version == MODEL_2_VERSION
    assert context.starting_cash == Decimal("10000")
    assert context.decision_pipeline.account_id == (
        MODEL_2_ACCOUNT_ID
    )
    assert not model1.exists()


def test_context_rebuilds_model2_portfolio(
    tmp_path,
    monkeypatch,
):
    _, model2 = configure_paths(
        tmp_path, monkeypatch
    )
    create_model2_account(model2)

    context = build_model2_decision_context()

    portfolio = context.portfolio_rebuilder.rebuild(
        account_id=context.account_id
    )

    assert portfolio.cash == Decimal("10000")
    assert portfolio.positions == {}
    assert context.trading_storage.count_orders() == 0
    assert context.trading_storage.count_fills() == 0


def test_missing_model2_database_fails_without_creating_it(
    tmp_path,
    monkeypatch,
):
    model1, model2 = configure_paths(
        tmp_path, monkeypatch
    )

    with pytest.raises(Model2DecisionContextError):
        build_model2_decision_context()

    assert not model1.exists()
    assert not model2.exists()


def test_wrong_account_fails_closed(
    tmp_path,
    monkeypatch,
):
    _, model2 = configure_paths(
        tmp_path, monkeypatch
    )
    create_model2_account(
        model2,
        account_id="model1-paper",
    )

    with pytest.raises(Model2DecisionContextError):
        build_model2_decision_context()


def test_different_starting_cash_fails_closed(
    tmp_path,
    monkeypatch,
):
    _, model2 = configure_paths(
        tmp_path, monkeypatch
    )
    create_model2_account(
        model2,
        starting_cash=5000,
    )

    with pytest.raises(Model2DecisionContextError):
        build_model2_decision_context()