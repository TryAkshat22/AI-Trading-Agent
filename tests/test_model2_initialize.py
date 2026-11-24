
from decimal import Decimal

import pytest

from database.account_storage import (
    AccountStorage,
    MultipleAccountsNotAllowedError,
)
from database.trading_storage import TradingStorage
from model2_initialize import initialize_model2


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


def test_initialization_creates_separate_account(
    tmp_path,
    monkeypatch,
):
    model1, model2 = configure_paths(
        tmp_path,
        monkeypatch,
    )

    initialize_model2()

    accounts = AccountStorage(model2)
    account = accounts.get_account("model2-paper")

    assert account is not None
    assert account.starting_cash == Decimal("10000")
    assert accounts.count_accounts() == 1
    assert not model1.exists()


def test_initialization_creates_no_orders_or_fills(
    tmp_path,
    monkeypatch,
):
    _, model2 = configure_paths(
        tmp_path,
        monkeypatch,
    )

    initialize_model2()

    trading = TradingStorage(model2)

    assert trading.count_orders() == 0
    assert trading.count_fills() == 0


def test_initialization_is_idempotent(
    tmp_path,
    monkeypatch,
):
    _, model2 = configure_paths(
        tmp_path,
        monkeypatch,
    )

    initialize_model2()
    initialize_model2()

    accounts = AccountStorage(model2)

    assert accounts.count_accounts() == 1


def test_foreign_account_blocks_initialization(
    tmp_path,
    monkeypatch,
):
    _, model2 = configure_paths(
        tmp_path,
        monkeypatch,
    )

    accounts = AccountStorage(model2)
    accounts.initialize()

    accounts.create_account(
        starting_cash=10000,
        account_id="different-account",
    )

    with pytest.raises(
        MultipleAccountsNotAllowedError
    ):
        initialize_model2()

    assert accounts.count_accounts() == 1