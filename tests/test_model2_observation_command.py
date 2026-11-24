
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from database.account_storage import AccountStorage
from database.storage import MarketDataStorage
from database.trading_storage import TradingStorage
from model2_config import MODEL_2_VERSION
from model2_observation_command import (
    Model2ObservationCommandError,
    discover_requirements,
)
from trading.orders import (
    Fill,
    Order,
    OrderSide,
    OrderStatus,
)


SESSION = date(2026, 9, 22)


def setup_database(
    tmp_path,
    *,
    existing_holding=False,
):
    db = tmp_path / "model2.db"

    MarketDataStorage(db).initialize()

    storage = TradingStorage(db)
    storage.initialize()

    accounts = AccountStorage(db)
    accounts.initialize()
    accounts.create_account(
        starting_cash=10000,
        account_id="model2-paper",
    )

    if existing_holding:
        held_order = Order(
            order_id="held-MSFT",
            ticker="MSFT",
            side=OrderSide.BUY,
            quantity=1,
            signal_timestamp_utc=datetime(
                2026, 9, 21, 20, 45,
                tzinfo=timezone.utc,
            ),
            execution_session=SESSION,
        )

        storage.save_order(
            held_order,
            model_version=MODEL_2_VERSION,
        )

        storage.save_fill(
            Fill(
                order_id=held_order.order_id,
                ticker="MSFT",
                side=OrderSide.BUY,
                quantity=1,
                reference_price=Decimal("100.00"),
                fill_price=Decimal("100.05"),
                gross_value=Decimal("100.05"),
                fees=Decimal("0.00"),
                slippage_cost=Decimal("0.05"),
                execution_session=SESSION,
                status=OrderStatus.FILLED,
                realized_pnl=Decimal("0.00"),
            )
        )

    pending_order = Order(
        order_id="pending-AAPL",
        ticker="AAPL",
        side=OrderSide.BUY,
        quantity=2,
        signal_timestamp_utc=datetime(
            2026, 9, 21, 20, 45,
            tzinfo=timezone.utc,
        ),
        execution_session=SESSION,
    )

    storage.save_order(
        pending_order,
        model_version=MODEL_2_VERSION,
    )

    return db, storage, pending_order.order_id


def test_discovers_pending_order_ticker(
    tmp_path,
):
    db, storage, order_id = setup_database(
        tmp_path
    )

    result = discover_requirements(
        db,
        SESSION,
    )

    assert result.order_ids == (order_id,)
    assert result.tickers == ("AAPL",)
    assert result.holding_tickers == ()
    assert storage.get_order_status(order_id) == "PENDING"
    assert storage.count_fills() == 0


def test_includes_existing_holding_ticker(
    tmp_path,
):
    db, storage, order_id = setup_database(
        tmp_path,
        existing_holding=True,
    )

    result = discover_requirements(
        db,
        SESSION,
    )

    assert result.order_ids == (order_id,)
    assert result.tickers == ("AAPL", "MSFT")
    assert result.holding_tickers == ("MSFT",)
    assert storage.get_order_status(order_id) == "PENDING"
    assert storage.count_fills() == 1


def test_expired_order_is_blocked(
    tmp_path,
):
    db, storage, order_id = setup_database(
        tmp_path
    )

    storage.reject_order(
        order_id=order_id,
        rejection_code="EXECUTION_WINDOW_EXPIRED",
        rejection_reason="Controlled test expiry.",
    )

    with pytest.raises(
        Model2ObservationCommandError,
        match="not eligible",
    ):
        discover_requirements(
            db,
            SESSION,
        )

    assert storage.count_fills() == 0


# ------------------------------------------------------------
# Observation-collection integration tests
# ------------------------------------------------------------

import sqlite3
from types import SimpleNamespace

import model2_observation_command
from model2_observation_command import (
    collect_required_observations,
)
from services.intraday_collector import (
    IntradayObservation,
    IntradayObservationStorage,
)


COLLECTION_SESSION = date(2026, 9, 22)

BAR_START = datetime(
    2026, 9, 22, 13, 45,
    tzinfo=timezone.utc,
)

RETRIEVED = datetime(
    2026, 9, 22, 13, 46, 5,
    tzinfo=timezone.utc,
)

CLOCK_START = datetime(
    2026, 9, 22, 13, 46, 10,
    tzinfo=timezone.utc,
)

CLOCK_BEFORE_COLLECTION = datetime(
    2026, 9, 22, 13, 46, 11,
    tzinfo=timezone.utc,
)

CLOCK_AFTER_COLLECTION = datetime(
    2026, 9, 22, 13, 46, 12,
    tzinfo=timezone.utc,
)

STALE_CHECK = datetime(
    2026, 9, 22, 13, 52,
    tzinfo=timezone.utc,
)


def controlled_clock(*values):
    timestamps = iter(values)
    return lambda: next(timestamps)


def setup_collection_case(
    tmp_path,
    monkeypatch,
    *,
    existing_holding=False,
):
    trading_db, trading, order_id = setup_database(
        tmp_path,
        existing_holding=existing_holding,
    )

    source_db = tmp_path / "observations.db"

    source_storage = IntradayObservationStorage(
        source_db
    )
    source_storage.initialize()

    monkeypatch.setenv(
        "TRADING_AGENT_DB_PATH",
        str(source_db),
    )

    monkeypatch.setenv(
        "PAPER_TRADING_MODEL2_DB_PATH",
        str(trading_db),
    )

    return (
        source_db,
        trading_db,
        trading,
        order_id,
    )


def install_controlled_collector(
    monkeypatch,
    *,
    fail_ticker=None,
    omit_ticker=None,
):
    """
    Substitute only the external collection step.

    Successful bars still pass through the real
    IntradayObservationStorage and real selector.
    """
    requested_batches = []

    class ControlledCollector:
        def __init__(self, storage):
            self.storage = storage

        def collect_batch(self, tickers):
            requested_batches.append(tuple(tickers))
            outcomes = []

            for ticker in tickers:
                if ticker == omit_ticker:
                    # Simulate a provider adapter that
                    # incorrectly omits a requested ticker.
                    continue

                if ticker == fail_ticker:
                    outcomes.append(
                        SimpleNamespace(
                            ticker=ticker,
                            error="Controlled provider failure",
                        )
                    )
                    continue

                close_price = (
                    101.0
                    if ticker == "AAPL"
                    else 100.0
                )

                observation = IntradayObservation(
                    ticker=ticker,
                    provider="controlled-test",
                    bar_start_utc=BAR_START,
                    retrieved_at_utc=RETRIEVED,
                    open=close_price - 1.0,
                    high=close_price + 1.0,
                    low=close_price - 2.0,
                    close=close_price,
                    volume=1000.0,
                )

                saved = self.storage.save(observation)

                assert saved

                outcomes.append(
                    SimpleNamespace(
                        ticker=ticker,
                        error=None,
                    )
                )

            return SimpleNamespace(
                outcomes=tuple(outcomes),
            )

    monkeypatch.setattr(
        model2_observation_command,
        "YahooIntradayCollector",
        ControlledCollector,
    )

    return requested_batches


def observation_count(source_db):
    with sqlite3.connect(source_db) as connection:
        return connection.execute(
            """
            SELECT COUNT(*)
            FROM intraday_observations
            """
        ).fetchone()[0]


def test_collection_validates_pending_order_price(
    tmp_path,
    monkeypatch,
):
    source_db, _, trading, order_id = (
        setup_collection_case(
            tmp_path,
            monkeypatch,
        )
    )

    batches = install_controlled_collector(
        monkeypatch
    )

    requirements, selected = (
        collect_required_observations(
            execution_session=COLLECTION_SESSION,
            clock=controlled_clock(
                CLOCK_START,
                CLOCK_BEFORE_COLLECTION,
                CLOCK_AFTER_COLLECTION,
            ),
        )
    )

    assert batches == [("AAPL",)]
    assert requirements.order_ids == (order_id,)
    assert requirements.tickers == ("AAPL",)
    assert set(selected) == {"AAPL"}

    assert selected["AAPL"].ticker == "AAPL"
    assert selected["AAPL"].reference_price == 101.0
    assert selected["AAPL"].bar_start_utc == BAR_START
    assert selected["AAPL"].retrieved_at_utc == RETRIEVED

    assert observation_count(source_db) == 1
    assert trading.get_order_status(order_id) == "PENDING"
    assert trading.count_fills() == 0


def test_collection_includes_and_validates_existing_holding(
    tmp_path,
    monkeypatch,
):
    source_db, _, trading, order_id = (
        setup_collection_case(
            tmp_path,
            monkeypatch,
            existing_holding=True,
        )
    )

    batches = install_controlled_collector(
        monkeypatch
    )

    requirements, selected = (
        collect_required_observations(
            execution_session=COLLECTION_SESSION,
            clock=controlled_clock(
                CLOCK_START,
                CLOCK_BEFORE_COLLECTION,
                CLOCK_AFTER_COLLECTION,
            ),
        )
    )

    assert batches == [("AAPL", "MSFT")]

    assert requirements.order_ids == (order_id,)
    assert requirements.holding_tickers == ("MSFT",)
    assert requirements.tickers == ("AAPL", "MSFT")

    assert set(selected) == {"AAPL", "MSFT"}
    assert selected["AAPL"].reference_price == 101.0
    assert selected["MSFT"].reference_price == 100.0

    assert observation_count(source_db) == 2
    assert trading.get_order_status(order_id) == "PENDING"

    # The existing MSFT fill must remain unchanged.
    # Observation collection must not create another fill.
    assert trading.count_fills() == 1


def test_partial_provider_failure_blocks_collection_result(
    tmp_path,
    monkeypatch,
):
    source_db, _, trading, order_id = (
        setup_collection_case(
            tmp_path,
            monkeypatch,
            existing_holding=True,
        )
    )

    batches = install_controlled_collector(
        monkeypatch,
        fail_ticker="MSFT",
    )

    with pytest.raises(
        Model2ObservationCommandError,
        match="Observation collection failed",
    ):
        collect_required_observations(
            execution_session=COLLECTION_SESSION,
            clock=controlled_clock(
                CLOCK_START,
                CLOCK_BEFORE_COLLECTION,
            ),
        )

    assert batches == [("AAPL", "MSFT")]

    # AAPL may have been collected successfully.
    # The command must still refuse to return an
    # incomplete set of validated observations.
    assert observation_count(source_db) == 1

    assert trading.get_order_status(order_id) == "PENDING"
    assert trading.count_fills() == 1


def test_stale_bar_blocks_collection_result(
    tmp_path,
    monkeypatch,
):
    source_db, _, trading, order_id = (
        setup_collection_case(
            tmp_path,
            monkeypatch,
        )
    )

    batches = install_controlled_collector(
        monkeypatch
    )

    # The 13:45 UTC bar is no longer fresh at
    # 13:52 UTC, even though the execution window
    # itself is still open.
    with pytest.raises(Exception):
        collect_required_observations(
            execution_session=COLLECTION_SESSION,
            clock=controlled_clock(
                CLOCK_START,
                CLOCK_BEFORE_COLLECTION,
                STALE_CHECK,
            ),
        )

    assert batches == [("AAPL",)]
    assert observation_count(source_db) == 1

    assert trading.get_order_status(order_id) == "PENDING"
    assert trading.count_fills() == 0


def test_incomplete_provider_response_blocks_collection_result(
    tmp_path,
    monkeypatch,
):
    source_db, _, trading, order_id = (
        setup_collection_case(
            tmp_path,
            monkeypatch,
            existing_holding=True,
        )
    )

    batches = install_controlled_collector(
        monkeypatch,
        omit_ticker="MSFT",
    )

    with pytest.raises(
        Model2ObservationCommandError,
        match="incomplete or duplicate ticker set",
    ):
        collect_required_observations(
            execution_session=COLLECTION_SESSION,
            clock=controlled_clock(
                CLOCK_START,
                CLOCK_BEFORE_COLLECTION,
            ),
        )

    assert batches == [("AAPL", "MSFT")]
    assert observation_count(source_db) == 1

    assert trading.get_order_status(order_id) == "PENDING"
    assert trading.count_fills() == 1