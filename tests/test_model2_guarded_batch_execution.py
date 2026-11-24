from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import model2_guarded_execution_command as command


SESSION = date(2026, 10, 27)

NOW = datetime(
    2026,
    10,
    27,
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


def create_test_database(
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
                status TEXT NOT NULL
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
            """
        )

        connection.executemany(
            """
            INSERT INTO paper_orders (
                order_id,
                ticker,
                side,
                quantity,
                execution_session,
                status
            )
            VALUES (?, ?, 'BUY', 1, ?, 'PENDING')
            """,
            (
                (
                    "order-1-AAPL",
                    "AAPL",
                    SESSION.isoformat(),
                ),
                (
                    "order-2-MSFT",
                    "MSFT",
                    SESSION.isoformat(),
                ),
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


def filled_tickers(
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


def install_common_fakes(
    monkeypatch,
    database: Path,
) -> None:
    model1_database = (
        database.parent / "model1.db"
    )

    observation_database = (
        database.parent / "observations.db"
    )

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

    def fake_discover_requirements(
        supplied_database,
        execution_session,
    ):
        assert Path(supplied_database) == database
        assert execution_session == SESSION

        order_ids = pending_orders(database)

        with sqlite3.connect(database) as connection:
            pending_ticker_rows = connection.execute(
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
            for row in pending_ticker_rows
        )

        holdings = filled_tickers(database)

        all_tickers = tuple(
            sorted(
                set(
                    pending_tickers
                    + holdings
                )
            )
        )

        return FakeRequirements(
            order_ids=order_ids,
            holding_tickers=holdings,
            tickers=all_tickers,
        )

    monkeypatch.setattr(
        command,
        "discover_requirements",
        fake_discover_requirements,
    )

    initial_requirements = (
        fake_discover_requirements(
            database,
            SESSION,
        )
    )

    observations = {
        ticker: FakeObservation(
            ticker=ticker,
            execution_session=SESSION,
        )
        for ticker
        in initial_requirements.tickers
    }

    def fake_collect_required_observations(
        *,
        execution_session,
        clock,
    ):
        assert execution_session == SESSION
        assert clock() == NOW

        current = fake_discover_requirements(
            database,
            SESSION,
        )

        assert (
            current
            == initial_requirements
        )

        return (
            initial_requirements,
            observations,
        )

    monkeypatch.setattr(
        command,
        "collect_required_observations",
        fake_collect_required_observations,
    )

    def fake_record_provenance(
        observation,
        *,
        now,
    ):
        assert now == NOW

        return SimpleNamespace(
            execution_run_id=(
                f"run-{observation.ticker}"
            )
        )

    monkeypatch.setattr(
        command,
        "record_model2_execution_observation",
        fake_record_provenance,
    )


def test_two_pending_orders_execute_sequentially(
    tmp_path,
    monkeypatch,
):
    """
    Two pending orders should execute in sequence.

    The second execution must see the position created
    by the first fill.
    """
    database = (
        tmp_path / "model2.db"
    )

    create_test_database(database)

    install_common_fakes(
        monkeypatch,
        database,
    )

    calls = []

    def fake_execute_model2_order(
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

        if order_id == "order-1-AAPL":
            assert (
                holding_observations
                == {}
            )

        elif order_id == "order-2-MSFT":
            assert set(
                holding_observations
            ) == {"AAPL"}

        else:
            pytest.fail(
                f"Unexpected order: {order_id}"
            )

        ticker = (
            execution_observation.ticker
        )

        fill_id = f"fill-{order_id}"
        attempt_id = (
            f"attempt-{order_id}"
        )
        run_id = f"run-{ticker}"

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
            execution_run_id=run_id,
            reference_price="100.00",
            fill_price="100.05",
        )

    monkeypatch.setattr(
        command,
        "execute_model2_order",
        fake_execute_model2_order,
    )

    result = (
        command.run_guarded_execution_batch(
            execution_session=SESSION,
            confirmation="MODEL2-PAPER",
            clock=lambda: NOW,
        )
    )

    assert result.filled_count == 2

    assert tuple(
        item.order_id
        for item in result.results
    ) == (
        "order-1-AAPL",
        "order-2-MSFT",
    )

    # Most important sequential-state assertion:
    # order 2 sees the AAPL holding created by order 1.
    assert calls == [
        (
            "order-1-AAPL",
            (),
        ),
        (
            "order-2-MSFT",
            ("AAPL",),
        ),
    ]

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


def test_second_order_failure_preserves_first_fill(
    tmp_path,
    monkeypatch,
):
    """
    If order 1 commits and order 2 is blocked, order 1
    must remain committed while order 2 remains PENDING.
    """
    database = (
        tmp_path / "model2.db"
    )

    create_test_database(database)

    install_common_fakes(
        monkeypatch,
        database,
    )

    calls = []

    def fake_execute_model2_order(
        *,
        order_id,
        execution_observation,
        holding_observations,
        clock,
    ):
        calls.append(order_id)

        assert clock() == NOW

        if order_id == "order-2-MSFT":
            # The second order must see the first
            # order's newly-created holding before
            # we simulate the blocker.
            assert set(
                holding_observations
            ) == {"AAPL"}

            raise RuntimeError(
                "simulated second-order risk block"
            )

        assert (
            order_id
            == "order-1-AAPL"
        )

        assert (
            holding_observations
            == {}
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
                    "attempt-order-1",
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
                VALUES (?, ?, 'AAPL', 1)
                """,
                (
                    "fill-order-1",
                    order_id,
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
            fill_id="fill-order-1",
            execution_run_id="run-AAPL",
            reference_price="100.00",
            fill_price="100.05",
        )

    monkeypatch.setattr(
        command,
        "execute_model2_order",
        fake_execute_model2_order,
    )

    with pytest.raises(
        RuntimeError,
        match=(
            "simulated second-order "
            "risk block"
        ),
    ):
        command.run_guarded_execution_batch(
            execution_session=SESSION,
            confirmation="MODEL2-PAPER",
            clock=lambda: NOW,
        )

    assert calls == [
        "order-1-AAPL",
        "order-2-MSFT",
    ]

    # First order remains legitimately committed.
    assert (
        order_status(
            database,
            "order-1-AAPL",
        )
        == "FILLED"
    )

    # Failed second order remains pending.
    assert (
        order_status(
            database,
            "order-2-MSFT",
        )
        == "PENDING"
    )

    assert pending_orders(
        database
    ) == (
        "order-2-MSFT",
    )

    assert count_fills(
        database
    ) == 1

    assert count_attempts(
        database
    ) == 1


def test_batch_does_not_duplicate_fills_or_attempts(
    tmp_path,
    monkeypatch,
):
    """
    Once both orders have been filled, a second batch
    invocation must not create another fill or attempt.
    """
    database = (
        tmp_path / "model2.db"
    )

    create_test_database(database)

    install_common_fakes(
        monkeypatch,
        database,
    )

    def fake_execute_model2_order(
        *,
        order_id,
        execution_observation,
        holding_observations,
        clock,
    ):
        ticker = (
            execution_observation.ticker
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
                    f"attempt-{order_id}",
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
                    f"fill-{order_id}",
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
            fill_id=f"fill-{order_id}",
            execution_run_id=(
                f"run-{ticker}"
            ),
            reference_price="100.00",
            fill_price="100.05",
        )

    monkeypatch.setattr(
        command,
        "execute_model2_order",
        fake_execute_model2_order,
    )

    first = (
        command.run_guarded_execution_batch(
            execution_session=SESSION,
            confirmation="MODEL2-PAPER",
            clock=lambda: NOW,
        )
    )

    assert first.filled_count == 2
    assert count_fills(database) == 2
    assert count_attempts(database) == 2

    # A second invocation has no pending orders.
    with pytest.raises(
        command.Model2GuardedExecutionError,
        match="No eligible pending",
    ):
        command.run_guarded_execution_batch(
            execution_session=SESSION,
            confirmation="MODEL2-PAPER",
            clock=lambda: NOW,
        )

    # Counts must remain unchanged.
    assert count_fills(database) == 2
    assert count_attempts(database) == 2


def test_batch_requires_explicit_confirmation(
    tmp_path,
    monkeypatch,
):
    database = (
        tmp_path / "model2.db"
    )

    create_test_database(database)

    install_common_fakes(
        monkeypatch,
        database,
    )

    with pytest.raises(
        command.Model2GuardedExecutionError,
        match="confirmation",
    ):
        command.run_guarded_execution_batch(
            execution_session=SESSION,
            confirmation="WRONG",
            clock=lambda: NOW,
        )

    assert count_fills(database) == 0
    assert count_attempts(database) == 0

    assert pending_orders(
        database
    ) == (
        "order-1-AAPL",
        "order-2-MSFT",
    )