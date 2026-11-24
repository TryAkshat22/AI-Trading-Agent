
from datetime import date, datetime, timedelta, timezone

import pytest

from services.intraday_collector import (
    IntradayObservation,
    IntradayObservationStorage,
)
from trading.flexible_observation_selector import (
    FlexibleObservationSelectionError,
    FlexibleObservationSelector,
)


UTC = timezone.utc
SESSION = date(2026, 9, 16)

BAR_START = datetime(
    2026, 9, 16, 14, 0,
    tzinfo=UTC,
)

RETRIEVED = datetime(
    2026, 9, 16, 14, 1, 10,
    tzinfo=UTC,
)

CHECKED = datetime(
    2026, 9, 16, 14, 2,
    tzinfo=UTC,
)


def make_observation(**changes):
    values = {
        "ticker": "AAPL",
        "provider": "yfinance-1m-observation",
        "bar_start_utc": BAR_START,
        "retrieved_at_utc": RETRIEVED,
        "open": 100.0,
        "high": 102.0,
        "low": 99.0,
        "close": 101.0,
        "volume": 1000.0,
    }

    values.update(changes)

    return IntradayObservation(**values)


def setup_selector(tmp_path, observations=()):
    database_path = tmp_path / "intraday.db"

    storage = IntradayObservationStorage(
        database_path
    )
    storage.initialize()

    for observation in observations:
        storage.save(observation)

    selector = FlexibleObservationSelector(
        database_path=database_path
    )

    return selector, storage


def test_selects_available_observation(tmp_path):
    selector, _ = setup_selector(
        tmp_path,
        [make_observation()],
    )

    result = selector.select(
        "AAPL",
        SESSION,
        CHECKED,
    )

    assert result.reference_price == 101.0
    assert result.price_field == "Close"


def test_selects_latest_available_observation(tmp_path):
    older = make_observation(
        bar_start_utc=BAR_START - timedelta(minutes=1),
        retrieved_at_utc=RETRIEVED - timedelta(minutes=1),
        close=100.0,
    )

    newer = make_observation(
        close=101.0,
    )

    selector, _ = setup_selector(
        tmp_path,
        [older, newer],
    )

    result = selector.select(
        "AAPL",
        SESSION,
        CHECKED,
    )

    assert result.reference_price == 101.0


def test_future_observation_not_used(tmp_path):
    future = make_observation(
        retrieved_at_utc=CHECKED + timedelta(seconds=1),
    )

    selector, _ = setup_selector(
        tmp_path,
        [future],
    )

    with pytest.raises(
        FlexibleObservationSelectionError
    ):
        selector.select(
            "AAPL",
            SESSION,
            CHECKED,
        )


def test_stale_observation_rejected(tmp_path):
    selector, _ = setup_selector(
        tmp_path,
        [make_observation()],
    )

    with pytest.raises(
        FlexibleObservationSelectionError
    ):
        selector.select(
            "AAPL",
            SESSION,
            CHECKED + timedelta(minutes=10),
        )


def test_wrong_ticker_not_selected(tmp_path):
    selector, _ = setup_selector(
        tmp_path,
        [make_observation()],
    )

    with pytest.raises(
        FlexibleObservationSelectionError
    ):
        selector.select(
            "MSFT",
            SESSION,
            CHECKED,
        )


def test_missing_database_not_created(tmp_path):
    database_path = tmp_path / "missing.db"

    selector = FlexibleObservationSelector(
        database_path=database_path
    )

    with pytest.raises(
        FlexibleObservationSelectionError
    ):
        selector.select(
            "AAPL",
            SESSION,
            CHECKED,
        )

    assert not database_path.exists()


def test_selection_does_not_change_observation_count(tmp_path):
    selector, storage = setup_selector(
        tmp_path,
        [make_observation()],
    )

    before = storage.count()

    selector.select(
        "AAPL",
        SESSION,
        CHECKED,
    )

    assert storage.count() == before