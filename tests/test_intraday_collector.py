
from datetime import (
    datetime,
    timedelta,
    timezone,
)

import pandas as pd
import pytest

from services.intraday_collector import (
    IntradayCollectionError,
    IntradayObservationStorage,
    YahooIntradayCollector,
)


SESSION = datetime(
    2026, 9, 16, 14, 0,
    tzinfo=timezone.utc,
)


def make_data(
    timestamp=None,
    price=100.0,
):
    if timestamp is None:
        timestamp = SESSION

    return pd.DataFrame(
        {
            "Open": [price],
            "High": [price + 1],
            "Low": [price - 1],
            "Close": [price],
            "Volume": [1000],
        },
        index=pd.DatetimeIndex(
            [timestamp]
        ),
    )


def build_collector(
    tmp_path,
    data=None,
    clock_time=None,
):
    storage = IntradayObservationStorage(
        tmp_path / "intraday.db"
    )
    storage.initialize()

    if data is None:
        data = make_data()

    if clock_time is None:
        clock_time = SESSION + timedelta(
            minutes=2
        )

    collector = YahooIntradayCollector(
        storage=storage,
        clock=lambda: clock_time,
        history_loader=lambda ticker: data,
    )

    return collector, storage


def test_valid_observation_saved(tmp_path):
    collector, storage = build_collector(
        tmp_path
    )

    assert collector.collect_one("AAPL") is True
    assert storage.count() == 1


def test_duplicate_bar_is_idempotent(tmp_path):
    collector, storage = build_collector(
        tmp_path
    )

    assert collector.collect_one("AAPL") is True
    assert collector.collect_one("AAPL") is False
    assert storage.count() == 1


def test_distinct_tickers_saved(tmp_path):
    collector, storage = build_collector(
        tmp_path
    )

    assert collector.collect_one("AAPL") is True
    assert collector.collect_one("MSFT") is True
    assert storage.count() == 2


def test_incomplete_bar_rejected(tmp_path):
    collector, storage = build_collector(
        tmp_path,
        clock_time=SESSION + timedelta(
            seconds=30
        ),
    )

    with pytest.raises(
        IntradayCollectionError
    ):
        collector.collect_one("AAPL")

    assert storage.count() == 0


def test_stale_bar_rejected(tmp_path):
    collector, storage = build_collector(
        tmp_path,
        clock_time=SESSION + timedelta(
            minutes=10
        ),
    )

    with pytest.raises(
        IntradayCollectionError
    ):
        collector.collect_one("AAPL")

    assert storage.count() == 0


def test_weekend_rejected(tmp_path):
    saturday = datetime(
        2026, 9, 19, 14, 2,
        tzinfo=timezone.utc,
    )

    collector, storage = build_collector(
        tmp_path,
        clock_time=saturday,
    )

    with pytest.raises(
        IntradayCollectionError
    ):
        collector.collect_one("AAPL")

    assert storage.count() == 0


def test_invalid_price_rejected(tmp_path):
    collector, storage = build_collector(
        tmp_path,
        data=make_data(price=0),
    )

    with pytest.raises(
        IntradayCollectionError
    ):
        collector.collect_one("AAPL")

    assert storage.count() == 0


def test_duplicate_timestamp_rejected(tmp_path):
    data = pd.concat(
        [make_data(), make_data()]
    )

    collector, storage = build_collector(
        tmp_path,
        data=data,
    )

    with pytest.raises(
        IntradayCollectionError
    ):
        collector.collect_one("AAPL")

    assert storage.count() == 0


def test_batch_continues_after_failure(tmp_path):
    storage = IntradayObservationStorage(
        tmp_path / "intraday.db"
    )
    storage.initialize()

    def loader(ticker):
        if ticker == "MSFT":
            raise RuntimeError(
                "Provider unavailable."
            )

        return make_data()

    collector = YahooIntradayCollector(
        storage=storage,
        clock=lambda: SESSION + timedelta(
            minutes=2
        ),
        history_loader=loader,
    )

    result = collector.collect_batch(
        ["AAPL", "MSFT", "NVDA"]
    )

    assert result.saved == 2
    assert result.failed == 1
    assert storage.count() == 2


def test_no_trading_tables_created(tmp_path):
    database = tmp_path / "intraday.db"

    collector, storage = build_collector(
        tmp_path
    )

    collector.collect_one("AAPL")

    import sqlite3

    with sqlite3.connect(database) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                """
            )
        }

    assert "intraday_observations" in tables
    assert "paper_orders" not in tables
    assert "paper_fills" not in tables