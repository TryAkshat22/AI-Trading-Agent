
from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import date, datetime, timezone

import pytest

from database.account_storage import AccountStorage
from database.storage import MarketDataStorage
from database.trading_storage import TradingStorage
from model2_execution_provenance import (
    record_model2_execution_observation,
)
from model2_locked_observation_verification import (
    Model2ObservationVerificationError,
    verify_locked_model2_observation,
)
from model2_locked_portfolio import (
    locked_test_model2_portfolio,
)
from services.intraday_collector import (
    IntradayObservation,
    IntradayObservationStorage,
)
from trading.flexible_execution_observation import (
    FlexibleExecutionObservationValidator,
)


SESSION = date(2026, 9, 18)

CHECKED = datetime(
    2026, 9, 18, 13, 46, 10,
    tzinfo=timezone.utc,
)


def setup_databases(tmp_path, monkeypatch):
    source_db = tmp_path / "source.db"
    trading_db = tmp_path / "trading.db"

    monkeypatch.setenv(
        "TRADING_AGENT_DB_PATH",
        str(source_db),
    )

    monkeypatch.setenv(
        "PAPER_TRADING_MODEL2_DB_PATH",
        str(trading_db),
    )

    source_storage = IntradayObservationStorage(
        source_db
    )
    source_storage.initialize()

    MarketDataStorage(trading_db).initialize()
    TradingStorage(trading_db).initialize()

    accounts = AccountStorage(trading_db)
    accounts.initialize()
    accounts.create_account(
        starting_cash=10000,
        account_id="model2-paper",
    )

    source = IntradayObservation(
        ticker="AAPL",
        provider="controlled-test",
        bar_start_utc=datetime(
            2026, 9, 18, 13, 45,
            tzinfo=timezone.utc,
        ),
        retrieved_at_utc=datetime(
            2026, 9, 18, 13, 46, 5,
            tzinfo=timezone.utc,
        ),
        open=100.0,
        high=102.0,
        low=99.0,
        close=101.0,
        volume=1000.0,
    )

    assert source_storage.save(source)

    observation = (
        FlexibleExecutionObservationValidator()
        .validate(
            observation=source,
            execution_session=SESSION,
            checked_at=CHECKED,
            expected_ticker="AAPL",
        )
    )

    provenance = record_model2_execution_observation(
        observation,
        now=CHECKED,
    )

    # After recording test provenance, configure a
    # DIFFERENT protected Model 2 path so the locked
    # test component can operate on trading_db.
    monkeypatch.setenv(
        "PAPER_TRADING_MODEL2_DB_PATH",
        str(tmp_path / "protected-live-model2.db"),
    )

    return (
        source_db,
        trading_db,
        observation,
        provenance.execution_run_id,
    )


def verify(db, source_db, observation, now=CHECKED):
    with locked_test_model2_portfolio(db) as (
        connection,
        portfolio,
    ):
        return verify_locked_model2_observation(
            connection=connection,
            source_database=source_db,
            observation=observation,
            now=now,
        )


def test_authentic_observation_returns_existing_run(
    tmp_path,
    monkeypatch,
):
    source_db, db, observation, expected_run = (
        setup_databases(tmp_path, monkeypatch)
    )

    result = verify(
        db,
        source_db,
        observation,
    )

    assert result == expected_run

    with sqlite3.connect(db) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM paper_fills"
        ).fetchone()[0] == 0


def test_modified_reference_price_is_blocked(
    tmp_path,
    monkeypatch,
):
    source_db, db, observation, _ = (
        setup_databases(tmp_path, monkeypatch)
    )

    altered = replace(
        observation,
        reference_price=999.0,
    )

    with pytest.raises(
        Model2ObservationVerificationError,
        match="differs",
    ):
        verify(
            db,
            source_db,
            altered,
        )


def test_missing_lineage_is_blocked(
    tmp_path,
    monkeypatch,
):
    source_db, db, observation, run_id = (
        setup_databases(tmp_path, monkeypatch)
    )

    # Deliberate modification in the TEMP database.
    with sqlite3.connect(db) as connection:
        connection.execute(
            """
            DELETE FROM
            model2_execution_observation_lineage
            WHERE execution_run_id = ?
            """,
            (run_id,),
        )

    with pytest.raises(
        Model2ObservationVerificationError,
        match="Exactly one",
    ):
        verify(
            db,
            source_db,
            observation,
        )


def test_stale_bar_is_blocked(
    tmp_path,
    monkeypatch,
):
    source_db, db, observation, _ = (
        setup_databases(tmp_path, monkeypatch)
    )

    too_late = datetime(
        2026, 9, 18, 13, 52,
        tzinfo=timezone.utc,
    )

    with pytest.raises(
        Model2ObservationVerificationError,
        match="stale",
    ):
        verify(
            db,
            source_db,
            observation,
            now=too_late,
        )