
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timezone

import pandas as pd
import pytest

from database.account_storage import AccountStorage
from database.execution_attempt_storage import ExecutionAttemptStorage
from database.storage import MarketDataStorage
from database.trading_storage import TradingStorage
from model2_config import MODEL_2_VERSION
from model2_execution_preflight import inspect_execution_prerequisites
from model2_execution_provenance import (
    record_model2_execution_observation,
)
from model2_integrated_executor import execute_test_model2_order
from services.intraday_collector import (
    IntradayObservationStorage,
    YahooIntradayCollector,
)
from trading.flexible_observation_selector import (
    FlexibleObservationSelector,
    FlexibleObservationSelectionError,
)
from trading.orders import Order, OrderSide


# A future-session date used ONLY with controlled test clocks.
SESSION = date(2026, 9, 22)

BAR_START = datetime(
    2026, 9, 22, 13, 45,
    tzinfo=timezone.utc,
)

COLLECTION_START = datetime(
    2026, 9, 22, 13, 46, 5,
    tzinfo=timezone.utc,
)

RETRIEVED = datetime(
    2026, 9, 22, 13, 46, 8,
    tzinfo=timezone.utc,
)

CHECKED = datetime(
    2026, 9, 22, 13, 46, 10,
    tzinfo=timezone.utc,
)

EXECUTION_START = datetime(
    2026, 9, 22, 13, 46, 11,
    tzinfo=timezone.utc,
)

EXECUTION_END = datetime(
    2026, 9, 22, 13, 46, 12,
    tzinfo=timezone.utc,
)

TOO_LATE = datetime(
    2026, 9, 22, 14, 30,
    tzinfo=timezone.utc,
)


def clock_sequence(*timestamps):
    iterator = iter(timestamps)
    return lambda: next(iterator)


def controlled_history(ticker):
    assert ticker == "AAPL"

    return pd.DataFrame(
        {
            "Open": [100.0],
            "High": [102.0],
            "Low": [99.0],
            "Close": [101.0],
            "Volume": [1000.0],
        },
        index=pd.DatetimeIndex(
            [BAR_START],
            name="Datetime",
        ),
    )


def setup_temporary_databases(
    tmp_path,
    monkeypatch,
):
    source_db = tmp_path / "source.db"
    trading_db = tmp_path / "model2.db"

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

    trading = TradingStorage(trading_db)
    trading.initialize()

    accounts = AccountStorage(trading_db)
    accounts.initialize()
    accounts.create_account(
        starting_cash=10000,
        account_id="model2-paper",
    )

    ExecutionAttemptStorage(trading_db).initialize()

    order = Order(
        order_id="offline-integration-AAPL",
        ticker="AAPL",
        side=OrderSide.BUY,
        quantity=2,
        signal_timestamp_utc=datetime(
            2026, 9, 21, 20, 45,
            tzinfo=timezone.utc,
        ),
        execution_session=SESSION,
    )

    trading.save_order(
        order,
        model_version=MODEL_2_VERSION,
    )

    return source_db, trading_db, trading, order.order_id


def collect_controlled_bar(
    source_db,
    *,
    history_loader=controlled_history,
):
    storage = IntradayObservationStorage(source_db)

    collector = YahooIntradayCollector(
        storage=storage,
        history_loader=history_loader,
        clock=clock_sequence(
            COLLECTION_START,
            RETRIEVED,
        ),
    )

    return collector.collect_batch(("AAPL",))


def observation_for_check(source_db, checked_at):
    selector = FlexibleObservationSelector(
        database_path=source_db,
    )

    return selector.select(
        ticker="AAPL",
        execution_session=SESSION,
        checked_at=checked_at,
    )


def table_count(database_path, table):
    # Table names below are fixed test constants.
    with sqlite3.connect(database_path) as connection:
        return connection.execute(
            f"SELECT COUNT(*) FROM {table}"
        ).fetchone()[0]


def test_collection_to_fill_uses_verified_observation(
    tmp_path,
    monkeypatch,
):
    source_db, trading_db, trading, order_id = (
        setup_temporary_databases(
            tmp_path,
            monkeypatch,
        )
    )

    # 1. Collect a real IntradayObservation object
    # through the production collector, but substitute
    # a deterministic DataFrame for the Yahoo response.
    collection = collect_controlled_bar(source_db)

    assert collection.saved == 1
    assert collection.failed == 0
    assert (
        table_count(
            source_db,
            "intraday_observations",
        )
        == 1
    )

    # 2. Select and validate the stored bar.
    observation = observation_for_check(
        source_db,
        CHECKED,
    )

    assert observation.ticker == "AAPL"
    assert observation.reference_price == 101.0
    assert observation.bar_start_utc == BAR_START
    assert observation.retrieved_at_utc == RETRIEVED

    # 3. Record authentic, minute-level provenance
    # in the TEMPORARY Model 2 trading database.
    provenance = record_model2_execution_observation(
        observation,
        now=CHECKED,
    )

    assert provenance.trading_database == (
        trading_db.resolve()
    )
    assert provenance.source_database == (
        source_db.resolve()
    )

    # 4. Run the existing READ-ONLY preflight while
    # the temporary Model 2 path is configured.
    pending = inspect_execution_prerequisites(
        execution_session=SESSION,
        now=CHECKED,
    )

    assert pending == (order_id,)

    # 5. The integrated executor is deliberately
    # test-only: point the configured protected Model 2
    # path elsewhere BEFORE invoking it. The actual
    # execution database remains trading_db.
    monkeypatch.setenv(
        "PAPER_TRADING_MODEL2_DB_PATH",
        str(tmp_path / "protected-live-model2.db"),
    )

    result = execute_test_model2_order(
        database_path=trading_db,
        order_id=order_id,
        execution_observation=observation,
        holding_observations={},
        clock=clock_sequence(
            EXECUTION_START,
            EXECUTION_END,
        ),
    )

    assert result.order_id == order_id
    assert (
        result.execution_run_id
        == provenance.execution_run_id
    )
    assert result.reference_price == "101.00"
    assert result.fill_price == "101.05"

    assert trading.get_order_status(order_id) == "FILLED"
    assert trading.count_fills() == 1

    assert (
        table_count(
            trading_db,
            "execution_attempts",
        )
        == 1
    )

    assert (
        table_count(
            trading_db,
            "fill_execution_lineage",
        )
        == 1
    )

    with sqlite3.connect(trading_db) as connection:
        row = connection.execute(
            """
            SELECT
                a.outcome,
                a.execution_run_id,
                l.execution_run_id
            FROM execution_attempts AS a
            JOIN paper_fills AS f
                ON f.order_id = a.order_id
            JOIN fill_execution_lineage AS l
                ON l.fill_id = f.fill_id
            WHERE a.order_id = ?
            """,
            (order_id,),
        ).fetchone()

    assert row == (
        "FILLED",
        provenance.execution_run_id,
        provenance.execution_run_id,
    )

    # The original observation database is not
    # used as Model 2's fill database.
    with sqlite3.connect(source_db) as connection:
        fills_table = connection.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table'
              AND name = 'paper_fills'
            """
        ).fetchone()

    assert fills_table is None


def test_collection_failure_stops_before_execution(
    tmp_path,
    monkeypatch,
):
    source_db, trading_db, trading, order_id = (
        setup_temporary_databases(
            tmp_path,
            monkeypatch,
        )
    )

    def unavailable_provider(ticker):
        raise RuntimeError(
            "Controlled provider outage"
        )

    collection = collect_controlled_bar(
        source_db,
        history_loader=unavailable_provider,
    )

    assert collection.saved == 0
    assert collection.failed == 1

    # With no collected observation, selection
    # must fail. Do not record provenance or
    # invoke the integrated executor.
    with pytest.raises(
        FlexibleObservationSelectionError,
    ):
        observation_for_check(
            source_db,
            CHECKED,
        )

    assert (
        table_count(
            source_db,
            "intraday_observations",
        )
        == 0
    )
    assert trading.get_order_status(order_id) == "PENDING"
    assert trading.count_fills() == 0
    assert (
        table_count(
            trading_db,
            "execution_attempts",
        )
        == 0
    )


def test_late_check_cannot_use_collected_bar(
    tmp_path,
    monkeypatch,
):
    source_db, trading_db, trading, order_id = (
        setup_temporary_databases(
            tmp_path,
            monkeypatch,
        )
    )

    collection = collect_controlled_bar(
        source_db
    )

    assert collection.saved == 1
    assert collection.failed == 0

    # A bar collected earlier cannot be treated
    # as a fresh execution price at 10:30 ET.
    # Selection fails before provenance or execution.
    with pytest.raises(
        FlexibleObservationSelectionError,
    ):
        observation_for_check(
            source_db,
            TOO_LATE,
        )

    assert trading.get_order_status(order_id) == "PENDING"
    assert trading.count_fills() == 0
    assert (
        table_count(
            trading_db,
            "execution_attempts",
        )
        == 0
    )