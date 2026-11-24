from __future__ import annotations

from datetime import (
    date,
    datetime,
    timezone,
)
from types import SimpleNamespace

import pytest

import model2_guarded_execution_command as guarded
from model2_guarded_execution_command import (
    Model2GuardedExecutionError,
    run_guarded_execution,
)
from model2_observation_command import (
    ObservationRequirements,
)


SESSION = date(2026, 10, 26)

NOW = datetime(
    2026, 10, 26, 13, 46,
    tzinfo=timezone.utc,
)


class FakePaths:
    def __init__(self, tmp_path):
        self.model1_database = (
            tmp_path / "model1.db"
        )
        self.model2_database = (
            tmp_path / "model2.db"
        )
        self.observation_database = (
            tmp_path / "observations.db"
        )

        self.model1_database.touch()
        self.model2_database.touch()
        self.observation_database.touch()


def fixed_clock():
    return NOW


def test_confirmation_is_required(
    tmp_path,
    monkeypatch,
):
    paths = FakePaths(tmp_path)

    monkeypatch.setattr(
        guarded,
        "get_model2_paths",
        lambda: paths,
    )

    with pytest.raises(
        Model2GuardedExecutionError,
        match="confirmation",
    ):
        run_guarded_execution(
            execution_session=SESSION,
            confirmation="",
            clock=fixed_clock,
        )


def test_multiple_pending_orders_are_blocked(
    tmp_path,
    monkeypatch,
):
    paths = FakePaths(tmp_path)

    monkeypatch.setattr(
        guarded,
        "get_model2_paths",
        lambda: paths,
    )

    monkeypatch.setattr(
        guarded,
        "inspect_execution_prerequisites",
        lambda **kwargs: (
            "order-A",
            "order-B",
        ),
    )

    with pytest.raises(
        Model2GuardedExecutionError,
        match="exactly one pending order",
    ):
        run_guarded_execution(
            execution_session=SESSION,
            confirmation="MODEL2-PAPER",
            clock=fixed_clock,
        )


def test_collection_state_change_is_blocked(
    tmp_path,
    monkeypatch,
):
    paths = FakePaths(tmp_path)

    monkeypatch.setattr(
        guarded,
        "get_model2_paths",
        lambda: paths,
    )

    monkeypatch.setattr(
        guarded,
        "inspect_execution_prerequisites",
        lambda **kwargs: (
            "order-A",
        ),
    )

    before = ObservationRequirements(
        order_ids=("order-A",),
        tickers=("AAPL",),
        holding_tickers=(),
    )

    after = ObservationRequirements(
        order_ids=("order-A",),
        tickers=("AAPL", "MSFT"),
        holding_tickers=("MSFT",),
    )

    monkeypatch.setattr(
        guarded,
        "discover_requirements",
        lambda *args, **kwargs: before,
    )

    monkeypatch.setattr(
        guarded,
        "collect_required_observations",
        lambda **kwargs: (
            after,
            {
                "AAPL": object(),
                "MSFT": object(),
            },
        ),
    )

    with pytest.raises(
        Model2GuardedExecutionError,
        match="changed before collection",
    ):
        run_guarded_execution(
            execution_session=SESSION,
            confirmation="MODEL2-PAPER",
            clock=fixed_clock,
        )


def test_incomplete_observation_set_is_blocked(
    tmp_path,
    monkeypatch,
):
    paths = FakePaths(tmp_path)

    monkeypatch.setattr(
        guarded,
        "get_model2_paths",
        lambda: paths,
    )

    monkeypatch.setattr(
        guarded,
        "inspect_execution_prerequisites",
        lambda **kwargs: (
            "order-A",
        ),
    )

    requirements = ObservationRequirements(
        order_ids=("order-A",),
        tickers=("AAPL", "MSFT"),
        holding_tickers=("MSFT",),
    )

    monkeypatch.setattr(
        guarded,
        "discover_requirements",
        lambda *args, **kwargs: requirements,
    )

    monkeypatch.setattr(
        guarded,
        "collect_required_observations",
        lambda **kwargs: (
            requirements,
            {
                "AAPL": object(),
            },
        ),
    )

    with pytest.raises(
        Model2GuardedExecutionError,
        match="observation set is incomplete",
    ):
        run_guarded_execution(
            execution_session=SESSION,
            confirmation="MODEL2-PAPER",
            clock=fixed_clock,
        )


def test_successful_orchestration_calls_executor_once(
    tmp_path,
    monkeypatch,
):
    paths = FakePaths(tmp_path)

    monkeypatch.setattr(
        guarded,
        "get_model2_paths",
        lambda: paths,
    )

    requirements = ObservationRequirements(
        order_ids=("order-A",),
        tickers=("AAPL",),
        holding_tickers=(),
    )

    observation = SimpleNamespace(
        ticker="AAPL"
    )

    preflight_calls = []

    def fake_preflight(**kwargs):
        preflight_calls.append(kwargs)
        return ("order-A",)

    monkeypatch.setattr(
        guarded,
        "inspect_execution_prerequisites",
        fake_preflight,
    )

    monkeypatch.setattr(
        guarded,
        "discover_requirements",
        lambda *args, **kwargs: requirements,
    )

    monkeypatch.setattr(
        guarded,
        "collect_required_observations",
        lambda **kwargs: (
            requirements,
            {
                "AAPL": observation,
            },
        ),
    )

    monkeypatch.setattr(
        guarded,
        "record_model2_execution_observation",
        lambda observation, now: (
            SimpleNamespace(
                execution_run_id="run-1"
            )
        ),
    )

    monkeypatch.setattr(
        guarded,
        "_load_ticker",
        lambda database, order_id: "AAPL",
    )

    executor_calls = []

    def fake_executor(**kwargs):
        executor_calls.append(kwargs)

        return SimpleNamespace(
            order_id="order-A",
            fill_id="fill-1",
            execution_run_id="run-1",
            reference_price="101.00",
            fill_price="101.05",
        )

    monkeypatch.setattr(
        guarded,
        "execute_model2_order",
        fake_executor,
    )

    result = run_guarded_execution(
        execution_session=SESSION,
        confirmation="MODEL2-PAPER",
        clock=fixed_clock,
    )

    assert result.order_id == "order-A"
    assert result.ticker == "AAPL"
    assert result.fill_id == "fill-1"
    assert result.execution_run_id == "run-1"

    assert len(preflight_calls) == 2
    assert len(executor_calls) == 1

    assert (
        executor_calls[0]["order_id"]
        == "order-A"
    )

    assert (
        executor_calls[0][
            "execution_observation"
        ]
        is observation
    )

    assert (
        executor_calls[0][
            "holding_observations"
        ]
        == {}
    )