
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timezone

import pytest

from database.account_storage import AccountStorage
from database.storage import MarketDataStorage
from database.trading_storage import TradingStorage
from model2_execution_provenance import (
    Model2ExecutionProvenanceError,
    record_model2_execution_observation,
)
from services.intraday_collector import (
    IntradayObservation,
    IntradayObservationStorage,
)
from trading.flexible_execution_observation import (
    FlexibleExecutionObservationValidator,
)


SESSION = date(2026, 9, 18)

BAR_START = datetime(
    2026, 9, 18, 13, 45,
    tzinfo=timezone.utc,
)

RETRIEVED = datetime(
    2026, 9, 18, 13, 46, 5,
    tzinfo=timezone.utc,
)

CHECKED = datetime(
    2026, 9, 18, 13, 46, 10,
    tzinfo=timezone.utc,
)


def setup_databases(tmp_path, monkeypatch):
    original = tmp_path / "original.db"
    model2 = tmp_path / "model2.db"

    monkeypatch.setenv(
        "TRADING_AGENT_DB_PATH",
        str(original),
    )
    monkeypatch.setenv(
        "PAPER_TRADING_MODEL2_DB_PATH",
        str(model2),
    )

    source_storage = IntradayObservationStorage(
        original
    )
    source_storage.initialize()

    market_storage = MarketDataStorage(model2)
    market_storage.initialize()

    accounts = AccountStorage(model2)
    accounts.initialize()
    accounts.create_account(
        starting_cash=10000,
        account_id="model2-paper",
    )

    trading = TradingStorage(model2)
    trading.initialize()

    source = IntradayObservation(
        ticker="AAPL",
        provider="controlled-test",
        bar_start_utc=BAR_START,
        retrieved_at_utc=RETRIEVED,
        open=100.0,
        high=102.0,
        low=99.0,
        close=101.0,
        volume=1000.0,
    )

    assert source_storage.save(source)

    validated = (
        FlexibleExecutionObservationValidator()
        .validate(
            observation=source,
            execution_session=SESSION,
            checked_at=CHECKED,
            expected_ticker="AAPL",
        )
    )

    return original, model2, validated


def test_records_exact_original_observation(
    tmp_path,
    monkeypatch,
):
    original, model2, validated = setup_databases(
        tmp_path,
        monkeypatch,
    )

    result = record_model2_execution_observation(
        validated,
        now=CHECKED,
    )

    assert result.source_database == original.resolve()
    assert result.trading_database == model2.resolve()
    assert result.reference_price == 101.0

    with sqlite3.connect(model2) as connection:
        row = connection.execute(
            """
            SELECT
                i.run_id,
                l.source_observation_id,
                l.bar_start_utc,
                l.close_price
            FROM ingestion_runs AS i
            JOIN model2_execution_observation_lineage AS l
                ON l.execution_run_id = i.run_id
            WHERE i.run_id = ?
            """,
            (result.execution_run_id,),
        ).fetchone()

    assert row is not None
    assert row[1] == result.source_observation_id
    assert row[2] == BAR_START.isoformat()
    assert row[3] == 101.0

    trading = TradingStorage(model2)
    assert trading.count_orders() == 0
    assert trading.count_fills() == 0


def test_duplicate_observation_reuses_existing_run(
    tmp_path,
    monkeypatch,
):
    _, model2, validated = setup_databases(
        tmp_path,
        monkeypatch,
    )

    first = record_model2_execution_observation(
        validated,
        now=CHECKED,
    )

    second = record_model2_execution_observation(
        validated,
        now=CHECKED,
    )

    assert second.execution_run_id == first.execution_run_id
    assert (
        second.source_observation_id
        == first.source_observation_id
    )

    with sqlite3.connect(model2) as connection:
        lineage_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM model2_execution_observation_lineage
            """
        ).fetchone()[0]

        run_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM ingestion_runs
            """
        ).fetchone()[0]

    assert lineage_count == 1
    assert run_count == 1


def test_stale_observation_cannot_be_recorded(
    tmp_path,
    monkeypatch,
):
    _, model2, validated = setup_databases(
        tmp_path,
        monkeypatch,
    )

    with pytest.raises(Exception, match="stale"):
        record_model2_execution_observation(
            validated,
            now=datetime(
                2026, 9, 18, 13, 52,
                tzinfo=timezone.utc,
            ),
        )

    with sqlite3.connect(model2) as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM ingestion_runs"
        ).fetchone()[0]

    assert count == 0


def test_modified_price_cannot_be_recorded(
    tmp_path,
    monkeypatch,
):
    from dataclasses import replace

    _, model2, validated = setup_databases(
        tmp_path,
        monkeypatch,
    )

    altered = replace(
        validated,
        reference_price=999.0,
    )

    with pytest.raises(
        Model2ExecutionProvenanceError,
        match="differs",
    ):
        record_model2_execution_observation(
            altered,
            now=CHECKED,
        )

    with sqlite3.connect(model2) as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM ingestion_runs"
        ).fetchone()[0]

    assert count == 0

def test_same_observation_can_be_shared_by_two_orders(
    tmp_path,
    monkeypatch,
):
    _, model2, validated = setup_databases(
        tmp_path,
        monkeypatch,
    )

    first = record_model2_execution_observation(
        validated,
        now=CHECKED,
    )

    second = record_model2_execution_observation(
        validated,
        now=CHECKED,
    )

    assert second.execution_run_id == first.execution_run_id
    assert (
        second.source_observation_id
        == first.source_observation_id
    )

    with sqlite3.connect(model2) as connection:
        runs = connection.execute(
            """
            SELECT COUNT(*)
            FROM model2_execution_observation_lineage
            """
        ).fetchone()[0]

    assert runs == 1