from __future__ import annotations

import pytest

from database.account_storage import (
    AccountStorage,
    DuplicateAccountError,
    MultipleAccountsNotAllowedError,
)


def test_database_allows_one_account(
    tmp_path,
):

    storage = AccountStorage(
        tmp_path / "test.db"
    )

    storage.initialize()

    created = storage.create_account(
        10_000
    )

    assert (
        created.account_id
        == "model1-paper"
    )

    assert (
        storage.count_accounts()
        == 1
    )


def test_second_different_account_is_rejected(
    tmp_path,
):

    storage = AccountStorage(
        tmp_path / "test.db"
    )

    storage.initialize()

    storage.create_account(
        10_000,
        account_id="model1-paper",
    )

    with pytest.raises(
        MultipleAccountsNotAllowedError
    ):
        storage.create_account(
            25_000,
            account_id="model2-paper",
        )

    assert (
        storage.count_accounts()
        == 1
    )

    assert (
        storage.get_account(
            "model2-paper"
        )
        is None
    )


def test_duplicate_same_account_still_uses_duplicate_error(
    tmp_path,
):

    storage = AccountStorage(
        tmp_path / "test.db"
    )

    storage.initialize()

    storage.create_account(
        10_000,
        account_id="model1-paper",
    )

    with pytest.raises(
        DuplicateAccountError
    ):
        storage.create_account(
            10_000,
            account_id="model1-paper",
        )

    assert (
        storage.count_accounts()
        == 1
    )


def test_get_or_create_returns_existing_account(
    tmp_path,
):

    storage = AccountStorage(
        tmp_path / "test.db"
    )

    storage.initialize()

    original = storage.create_account(
        10_000
    )

    retrieved = storage.get_or_create(
        50_000
    )

    assert (
        retrieved.account_id
        == original.account_id
    )

    # get_or_create must not silently
    # overwrite starting capital.
    assert (
        retrieved.starting_cash
        == original.starting_cash
    )

    assert (
        storage.count_accounts()
        == 1
    )


def test_get_or_create_rejects_different_account(
    tmp_path,
):

    storage = AccountStorage(
        tmp_path / "test.db"
    )

    storage.initialize()

    storage.create_account(
        10_000,
        account_id="model1-paper",
    )

    with pytest.raises(
        MultipleAccountsNotAllowedError
    ):
        storage.get_or_create(
            20_000,
            account_id="another-account",
        )

    assert (
        storage.count_accounts()
        == 1
    )