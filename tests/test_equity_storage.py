from datetime import (
    date,
    datetime,
    timezone,
)
from decimal import Decimal

import pytest

from database.equity_storage import (
    EquitySnapshotConflictError,
    EquityStorage,
)


SESSION = date(
    2026,
    9,
    14,
)


def make_storage(
    tmp_path,
):

    storage = EquityStorage(
        tmp_path
        / "equity.db"
    )

    storage.initialize()

    return storage


def save_basic(
    storage,
    **overrides,
):

    values = {
        "valuation_session": SESSION,
        "starting_cash": 10000,
        "cash": 9000,
        "market_value": 1100,
        "total_equity": 10100,
        "realized_pnl": 0,
        "unrealized_pnl": 100,
        "total_pnl": 100,
        "total_return_pct": 1,
        "exposure_pct": (
            Decimal(
                "10.891089"
            )
        ),
        "open_positions": 1,
        "recorded_at_utc": datetime(
            2026,
            9,
            14,
            20,
            0,
            tzinfo=timezone.utc,
        ),
    }

    values.update(
        overrides
    )

    return storage.save_snapshot(
        **values
    )


def test_save_and_get_snapshot(
    tmp_path,
):

    storage = make_storage(
        tmp_path
    )

    saved = save_basic(
        storage
    )

    loaded = storage.get_snapshot(
        SESSION
    )

    assert loaded is not None
    assert (
        loaded.snapshot_id
        == saved.snapshot_id
    )
    assert (
        loaded.total_equity
        == Decimal(
            "10100"
        )
    )


def test_exact_duplicate_is_idempotent(
    tmp_path,
):

    storage = make_storage(
        tmp_path
    )

    first = save_basic(
        storage
    )

    second = save_basic(
        storage
    )

    assert (
        first.snapshot_id
        == second.snapshot_id
    )

    assert (
        storage.count_snapshots()
        == 1
    )


def test_different_same_day_snapshot_conflicts(
    tmp_path,
):

    storage = make_storage(
        tmp_path
    )

    save_basic(
        storage
    )

    with pytest.raises(
        EquitySnapshotConflictError
    ):

        save_basic(
            storage,
            total_equity=10200,
        )


def test_list_snapshots_sorted_by_session(
    tmp_path,
):

    storage = make_storage(
        tmp_path
    )

    save_basic(
        storage,
        valuation_session=date(
            2026,
            9,
            15,
        ),
    )

    save_basic(
        storage,
        valuation_session=date(
            2026,
            9,
            14,
        ),
    )

    snapshots = (
        storage.list_snapshots()
    )

    assert [
        snapshot.valuation_session
        for snapshot in snapshots
    ] == [
        date(
            2026,
            9,
            14,
        ),
        date(
            2026,
            9,
            15,
        ),
    ]


def test_account_and_model_are_separate_series(
    tmp_path,
):

    storage = make_storage(
        tmp_path
    )

    save_basic(
        storage,
        model_version="model-1",
    )

    save_basic(
        storage,
        model_version="model-2",
    )

    assert (
        storage.count_snapshots(
            model_version="model-1"
        )
        == 1
    )

    assert (
        storage.count_snapshots(
            model_version="model-2"
        )
        == 1
    )


def test_naive_recorded_time_rejected(
    tmp_path,
):

    storage = make_storage(
        tmp_path
    )

    with pytest.raises(
        ValueError
    ):

        save_basic(
            storage,
            recorded_at_utc=datetime(
                2026,
                9,
                14,
                20,
                0,
            ),
        )


def test_negative_open_positions_rejected(
    tmp_path,
):

    storage = make_storage(
        tmp_path
    )

    with pytest.raises(
        ValueError
    ):

        save_basic(
            storage,
            open_positions=-1,
        )


def test_missing_snapshot_returns_none(
    tmp_path,
):

    storage = make_storage(
        tmp_path
    )

    assert (
        storage.get_snapshot(
            SESSION
        )
        is None
    )