from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import model2_guarded_execution_command as command
from model2_production_executor import (
    Model2ProductionExecutionError,
)


SESSION = date(2026, 10, 29)

NOW = datetime(
    2026,
    10,
    29,
    14,
    0,
    tzinfo=timezone.utc,
)


@dataclass(frozen=True)
class FakeRequirements:
    order_ids: tuple[str, ...]
    holding_tickers: tuple[str, ...]
    tickers: tuple[str, ...]


@dataclass(frozen=True)
class FakeObservation:
    ticker: str
    execution_session: date


def create_database(
    database: Path,
) -> None:
    with sqlite3.connect(database) as connection:
        connection.executescript(
            """
            CREATE TABLE paper_orders (
                order_id TEXT PRIMARY KEY,
                ticker TEXT NOT NULL,
                side TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                execution_session TEXT NOT NULL,
                status TEXT NOT NULL,
                model_version TEXT NOT NULL
            );

            CREATE TABLE paper_fills (
                fill_id TEXT PRIMARY KEY,
                order_id TEXT NOT NULL,
                ticker TEXT NOT NULL,
                quantity INTEGER NOT NULL
            );

            CREATE TABLE execution_attempts (
                attempt_id TEXT PRIMARY KEY,
                order_id TEXT NOT NULL,
                outcome TEXT NOT NULL
            );

            CREATE TABLE order_rejections (
                order_id TEXT NOT NULL,
                rejection_code TEXT NOT NULL,
                rejection_reason TEXT NOT NULL,
                rejected_at_utc TEXT NOT NULL
            );
            """
        )

        rows = (
            (
                "order-1-AAPL",
                "AAPL",
                "model-2-flexible",
            ),
            (
                "order-2-MSFT",
                "MSFT",
                "model-2-flexible",
            ),
            (
                "order-3-JNJ",
                "JNJ",
                "model-2-flexible",
            ),
        )

        connection.executemany(
            """
            INSERT INTO paper_orders (
                order_id,
                ticker,
                side,
                quantity,
                execution_session,
                status,
                model_version
            )
            VALUES (
                ?, ?, 'BUY', 1, ?, 'PENDING', ?
            )
            """,
            (
                (
                    order_id,
                    ticker,
                    SESSION.isoformat(),
                    model_version,
                )
                for (
                    order_id,
                    ticker,
                    model_version,
                )
                in rows
            ),
        )

        connection.commit()


def pending_orders(
    database: Path,
) -> tuple[str, ...]:
    with sqlite3.connect(database) as connection:
        rows = connection.execute(
            """
            SELECT order_id
            FROM paper_orders
            WHERE execution_session = ?
              AND status = 'PENDING'
            ORDER BY order_id
            """,
            (SESSION.isoformat(),),
        ).fetchall()

    return tuple(
        row[0]
        for row in rows
    )


def holding_tickers(
    database: Path,
) -> tuple[str, ...]:
    with sqlite3.connect(database) as connection:
        rows = connection.execute(
            """
            SELECT DISTINCT ticker
            FROM paper_fills
            ORDER BY ticker
            """
        ).fetchall()

    return tuple(
        row[0]
        for row in rows
    )


def order_status(
    database: Path,
    order_id: str,
) -> str:
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            """
            SELECT status
            FROM paper_orders
            WHERE order_id = ?
            """,
            (order_id,),
        ).fetchone()

    assert row is not None
    return row[0]


def count_fills(
    database: Path,
) -> int:
    with sqlite3.connect(database) as connection:
        return connection.execute(
            "SELECT COUNT(*) FROM paper_fills"
        ).fetchone()[0]


def count_attempts(
    database: Path,
) -> int:
    with sqlite3.connect(database) as connection:
        return connection.execute(
            """
            SELECT COUNT(*)
            FROM execution_attempts
            """
        ).fetchone()[0]


def count_rejections(
    database: Path,
) -> int:
    with sqlite3.connect(database) as connection:
        return connection.execute(
            """
            SELECT COUNT(*)
            FROM order_rejections
            """
        ).fetchone()[0]


def test_fill_then_risk_reject_then_continue(
    tmp_path,
    monkeypatch,
):
    database = (
        tmp_path / "model2.db"
    )

    model1_database = (
        tmp_path / "model1.db"
    )

    observation_database = (
        tmp_path / "observations.db"
    )

    create_database(database)

    monkeypatch.setattr(
        command,
        "get_model2_paths",
        lambda: SimpleNamespace(
            model2_database=database,
            model1_database=model1_database,
            observation_database=observation_database,
        ),
    )

    def fake_preflight(
        *,
        execution_session,
        now,
    ):
        assert execution_session == SESSION
        assert now == NOW

        return pending_orders(database)

    monkeypatch.setattr(
        command,
        "inspect_execution_prerequisites",
        fake_preflight,
    )

    def fake_requirements(
        supplied_database,
        execution_session,
    ):
        assert Path(supplied_database) == database
        assert execution_session == SESSION

        pending = pending_orders(database)

        with sqlite3.connect(database) as connection:
            rows = connection.execute(
                """
                SELECT ticker
                FROM paper_orders
                WHERE execution_session = ?
                  AND status = 'PENDING'
                ORDER BY order_id
                """,
                (SESSION.isoformat(),),
            ).fetchall()

        pending_tickers = tuple(
            row[0]
            for row in rows
        )

        holdings = holding_tickers(
            database
        )

        tickers = tuple(
            sorted(
                set(
                    pending_tickers
                    + holdings
                )
            )
        )

        return FakeRequirements(
            order_ids=pending,
            holding_tickers=holdings,
            tickers=tickers,
        )

    monkeypatch.setattr(
        command,
        "discover_requirements",
        fake_requirements,
    )

    initial = fake_requirements(
        database,
        SESSION,
    )

    observations = {
        ticker: FakeObservation(
            ticker=ticker,
            execution_session=SESSION,
        )
        for ticker in initial.tickers
    }

    def fake_collect(
        *,
        execution_session,
        clock,
    ):
        assert execution_session == SESSION
        assert clock() == NOW

        return (
            initial,
            observations,
        )

    monkeypatch.setattr(
        command,
        "collect_required_observations",
        fake_collect,
    )

    monkeypatch.setattr(
        command,
        "record_model2_execution_observation",
        lambda observation, now: (
            SimpleNamespace(
                execution_run_id=(
                    f"run-{observation.ticker}"
                )
            )
        ),
    )

    calls = []

    def fake_execute(
        *,
        order_id,
        execution_observation,
        holding_observations,
        clock,
    ):
        calls.append(
            (
                order_id,
                tuple(
                    sorted(
                        holding_observations
                    )
                ),
            )
        )

        assert clock() == NOW

        ticker = (
            execution_observation.ticker
        )

        if order_id == "order-2-MSFT":
            raise Model2ProductionExecutionError(
                "Execution-time risk rejected the trade: "
                "simulated portfolio concentration limit"
            )

        fill_id = (
            f"fill-{order_id}"
        )

        attempt_id = (
            f"attempt-{order_id}"
        )

        with sqlite3.connect(
            database
        ) as connection:
            connection.execute(
                """
                INSERT INTO execution_attempts (
                    attempt_id,
                    order_id,
                    outcome
                )
                VALUES (?, ?, 'FILLED')
                """,
                (
                    attempt_id,
                    order_id,
                ),
            )

            connection.execute(
                """
                INSERT INTO paper_fills (
                    fill_id,
                    order_id,
                    ticker,
                    quantity
                )
                VALUES (?, ?, ?, 1)
                """,
                (
                    fill_id,
                    order_id,
                    ticker,
                ),
            )

            changed = connection.execute(
                """
                UPDATE paper_orders
                SET status = 'FILLED'
                WHERE order_id = ?
                  AND status = 'PENDING'
                """,
                (order_id,),
            )

            assert changed.rowcount == 1

            connection.commit()

        return SimpleNamespace(
            order_id=order_id,
            fill_id=fill_id,
            execution_run_id=(
                f"run-{ticker}"
            ),
            reference_price="100.00",
            fill_price="100.05",
        )

    monkeypatch.setattr(
        command,
        "execute_model2_order",
        fake_execute,
    )

    result = (
        command.run_guarded_execution_batch(
            execution_session=SESSION,
            confirmation="MODEL2-PAPER",
            clock=lambda: NOW,
        )
    )

    assert result.filled_count == 2
    assert result.rejected_count == 1

    assert tuple(
        item.order_id
        for item in result.results
    ) == (
        "order-1-AAPL",
        "order-3-JNJ",
    )

    assert tuple(
        item.order_id
        for item in result.rejections
    ) == (
        "order-2-MSFT",
    )

    assert (
        order_status(
            database,
            "order-1-AAPL",
        )
        == "FILLED"
    )

    assert (
        order_status(
            database,
            "order-2-MSFT",
        )
        == "REJECTED"
    )

    assert (
        order_status(
            database,
            "order-3-JNJ",
        )
        == "FILLED"
    )

    assert pending_orders(
        database
    ) == ()

    assert count_fills(
        database
    ) == 2

    assert count_attempts(
        database
    ) == 2

    assert count_rejections(
        database
    ) == 1

    # Order 3 must see the AAPL holding created by
    # order 1 even though order 2 was rejected.
    assert calls == [
        (
            "order-1-AAPL",
            (),
        ),
        (
            "order-2-MSFT",
            ("AAPL",),
        ),
        (
            "order-3-JNJ",
            ("AAPL",),
        ),
    ]


def test_non_risk_failure_still_stops_batch(
    tmp_path,
    monkeypatch,
):
    database = (
        tmp_path / "model2.db"
    )

    model1_database = (
        tmp_path / "model1.db"
    )

    observation_database = (
        tmp_path / "observations.db"
    )

    create_database(database)

    monkeypatch.setattr(
        command,
        "get_model2_paths",
        lambda: SimpleNamespace(
            model2_database=database,
            model1_database=model1_database,
            observation_database=observation_database,
        ),
    )

    monkeypatch.setattr(
        command,
        "inspect_execution_prerequisites",
        lambda **kwargs: pending_orders(
            database
        ),
    )

    def fake_requirements(
        supplied_database,
        execution_session,
    ):
        pending = pending_orders(
            database
        )

        with sqlite3.connect(
            database
        ) as connection:
            rows = connection.execute(
                """
                SELECT ticker
                FROM paper_orders
                WHERE status = 'PENDING'
                ORDER BY order_id
                """
            ).fetchall()

        pending_tickers = tuple(
            row[0]
            for row in rows
        )

        holdings = holding_tickers(
            database
        )

        return FakeRequirements(
            order_ids=pending,
            holding_tickers=holdings,
            tickers=tuple(
                sorted(
                    set(
                        pending_tickers
                        + holdings
                    )
                )
            ),
        )

    monkeypatch.setattr(
        command,
        "discover_requirements",
        fake_requirements,
    )

    initial = fake_requirements(
        database,
        SESSION,
    )

    observations = {
        ticker: FakeObservation(
            ticker=ticker,
            execution_session=SESSION,
        )
        for ticker in initial.tickers
    }

    monkeypatch.setattr(
        command,
        "collect_required_observations",
        lambda **kwargs: (
            initial,
            observations,
        ),
    )

    monkeypatch.setattr(
        command,
        "record_model2_execution_observation",
        lambda observation, now: (
            SimpleNamespace(
                execution_run_id=(
                    f"run-{observation.ticker}"
                )
            )
        ),
    )

    def fake_execute(
        *,
        order_id,
        execution_observation,
        holding_observations,
        clock,
    ):
        if order_id == "order-1-AAPL":
            with sqlite3.connect(
                database
            ) as connection:
                connection.execute(
                    """
                    INSERT INTO execution_attempts (
                        attempt_id,
                        order_id,
                        outcome
                    )
                    VALUES (
                        'attempt-order-1',
                        ?,
                        'FILLED'
                    )
                    """,
                    (order_id,),
                )

                connection.execute(
                    """
                    INSERT INTO paper_fills (
                        fill_id,
                        order_id,
                        ticker,
                        quantity
                    )
                    VALUES (
                        'fill-order-1',
                        ?,
                        'AAPL',
                        1
                    )
                    """,
                    (order_id,),
                )

                connection.execute(
                    """
                    UPDATE paper_orders
                    SET status = 'FILLED'
                    WHERE order_id = ?
                    """,
                    (order_id,),
                )

                connection.commit()

            return SimpleNamespace(
                order_id=order_id,
                fill_id="fill-order-1",
                execution_run_id="run-AAPL",
                reference_price="100",
                fill_price="100.05",
            )

        raise Model2ProductionExecutionError(
            "Observation is stale."
        )

    monkeypatch.setattr(
        command,
        "execute_model2_order",
        fake_execute,
    )

    with pytest.raises(
        Model2ProductionExecutionError,
        match="Observation is stale",
    ):
        command.run_guarded_execution_batch(
            execution_session=SESSION,
            confirmation="MODEL2-PAPER",
            clock=lambda: NOW,
        )

    assert (
        order_status(
            database,
            "order-1-AAPL",
        )
        == "FILLED"
    )

    assert (
        order_status(
            database,
            "order-2-MSFT",
        )
        == "PENDING"
    )

    assert (
        order_status(
            database,
            "order-3-JNJ",
        )
        == "PENDING"
    )

    assert count_fills(
        database
    ) == 1

    assert count_rejections(
        database
    ) == 0