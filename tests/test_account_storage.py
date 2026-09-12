import pytest

from database.account_storage import (
    AccountAlreadyExistsError,
    AccountStorage,
)
from trading.portfolio import money


def test_account_is_created(
    tmp_path,
):

    storage = AccountStorage(
        tmp_path / "test.db"
    )

    storage.initialize()

    account = storage.create_account(
        10_000
    )

    assert account.starting_cash == money(
        10_000
    )


def test_account_survives_reload(
    tmp_path,
):

    db = tmp_path / "test.db"

    first = AccountStorage(db)
    first.initialize()

    first.create_account(
        10_000
    )

    second = AccountStorage(db)
    second.initialize()

    account = second.get_account()

    assert account is not None

    assert account.starting_cash == money(
        10_000
    )


def test_duplicate_account_is_rejected(
    tmp_path,
):

    storage = AccountStorage(
        tmp_path / "test.db"
    )

    storage.initialize()

    storage.create_account(
        10_000
    )

    with pytest.raises(
        AccountAlreadyExistsError
    ):
        storage.create_account(
            10_000
        )