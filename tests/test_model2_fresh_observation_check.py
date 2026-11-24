
from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest

from model2_config import MODEL_2_VERSION
from model2_fresh_observation_check import (
    Model2FreshObservationError,
    collect_and_check_model2,
)
from services.intraday_collector import (
    CollectionBatchResult,
    CollectionOutcome,
    IntradayObservation,
    IntradayObservationStorage,
)
from trading.flexible_observation_selector import (
    FlexibleObservationSelector,
)


SESSION = date(2026, 9, 18)

START = datetime(
    2026, 9, 18, 13, 46, 5,
    tzinfo=timezone.utc,
)

FINISH = datetime(
    2026, 9, 18, 13, 46, 10,
    tzinfo=timezone.utc,
)

TOO_LATE = datetime(
    2026, 9, 18, 19, 30,
    tzinfo=timezone.utc,
)


class FakePendingQuery:
    def __init__(self, orders):
        self.orders = tuple(orders)

    def find_for_session(self, session):
        assert session == SESSION
        return self.orders


class FakeChecker:
    def __init__(self):
        self.calls = []

    def check(self, execution_session, checked_at):
        self.calls.append(
            (execution_session, checked_at)
        )
        return SimpleNamespace(
            eligible_count=1,
            ineligible_count=0,
        )


class FakeCollector:
    def __init__(
        self,
        storage,
        *,
        error=None,
        persist=True,
    ):
        self.storage = storage
        self.error = error
        self.persist = persist
        self.requested = None

    def collect_batch(self, tickers):
        self.requested = tuple(tickers)

        if self.persist and self.error is None:
            self.storage.save(
                IntradayObservation(
                    ticker="AAPL",
                    provider="controlled-test",
                    bar_start_utc=datetime(
                        2026, 9, 18, 13, 45,
                        tzinfo=timezone.utc,
                    ),
                    retrieved_at_utc=datetime(
                        2026, 9, 18, 13, 46, 7,
                        tzinfo=timezone.utc,
                    ),
                    open=100.0,
                    high=102.0,
                    low=99.0,
                    close=101.0,
                    volume=1000.0,
                )
            )

        return CollectionBatchResult(
            outcomes=(
                CollectionOutcome(
                    ticker="AAPL",
                    saved=self.persist
                    and self.error is None,
                    error=self.error,
                ),
            )
        )


def configure(tmp_path, monkeypatch):
    model1 = tmp_path / "model1.db"
    model2 = tmp_path / "model2.db"

    monkeypatch.setenv(
        "TRADING_AGENT_DB_PATH",
        str(model1),
    )
    monkeypatch.setenv(
        "PAPER_TRADING_MODEL2_DB_PATH",
        str(model2),
    )

    # Existing database files stand in for the two
    # already-initialized databases.
    model1.touch()
    model2.touch()

    order = SimpleNamespace(
        order_id="test-model2-AAPL",
        ticker="AAPL",
        model_version=MODEL_2_VERSION,
    )

    return model1, model2, order


def clock_sequence(*times):
    values = iter(times)
    return lambda: next(values)


def test_collection_then_eligibility_uses_separate_databases(
    tmp_path,
    monkeypatch,
):
    model1, model2, order = configure(
        tmp_path,
        monkeypatch,
    )

    checker = FakeChecker()
    captured = {}

    def collector_factory(storage):
        captured["storage"] = storage
        return FakeCollector(storage)

    def checker_factory(database_path, selector):
        captured["trading_database"] = database_path
        captured["selector"] = selector
        return checker

    result = collect_and_check_model2(
        SESSION,
        clock=clock_sequence(START, FINISH),
        pending_query_factory=lambda path: (
            FakePendingQuery([order])
        ),
        collector_factory=collector_factory,
        checker_factory=checker_factory,
    )

    assert result.pending_order_count == 1
    assert result.ready_order_count == 1
    assert (
        captured["storage"].database_path.resolve()
        == model1.resolve()
    )
    assert (
        captured["trading_database"]
        == model2.resolve()
    )
    assert checker.calls == [(SESSION, FINISH)]

    # This checks the real read-only selector against
    # the observation just written by the fake collector.
    observation = captured["selector"].select(
        ticker="AAPL",
        execution_session=SESSION,
        checked_at=FINISH,
    )

    assert observation.reference_price == 101.0

    assert IntradayObservationStorage(model1).count() == 1
    assert model2.stat().st_size == 0


def test_collection_failure_prevents_eligibility(
    tmp_path,
    monkeypatch,
):
    _, _, order = configure(tmp_path, monkeypatch)

    checker = FakeChecker()

    with pytest.raises(
        Model2FreshObservationError,
        match="collection failed",
    ):
        collect_and_check_model2(
            SESSION,
            clock=clock_sequence(START),
            pending_query_factory=lambda path: (
                FakePendingQuery([order])
            ),
            collector_factory=lambda storage: (
                FakeCollector(
                    storage,
                    error="Provider unavailable.",
                )
            ),
            checker_factory=lambda path, selector: checker,
        )

    assert checker.calls == []


def test_window_closing_during_collection_blocks_check(
    tmp_path,
    monkeypatch,
):
    _, _, order = configure(tmp_path, monkeypatch)

    checker = FakeChecker()

    with pytest.raises(
        Exception,
        match="Outside the Model 2 execution window",
    ):
        collect_and_check_model2(
            SESSION,
            clock=clock_sequence(START, TOO_LATE),
            pending_query_factory=lambda path: (
                FakePendingQuery([order])
            ),
            collector_factory=lambda storage: (
                FakeCollector(storage)
            ),
            checker_factory=lambda path, selector: checker,
        )

    assert checker.calls == []


def test_wrong_model_is_blocked_before_collection(
    tmp_path,
    monkeypatch,
):
    _, _, order = configure(tmp_path, monkeypatch)

    wrong_order = SimpleNamespace(
        order_id=order.order_id,
        ticker="AAPL",
        model_version="model-1",
    )

    called = []

    with pytest.raises(
        Model2FreshObservationError,
        match="unexpected model",
    ):
        collect_and_check_model2(
            SESSION,
            clock=clock_sequence(START),
            pending_query_factory=lambda path: (
                FakePendingQuery([wrong_order])
            ),
            collector_factory=lambda storage: (
                called.append(storage)
            ),
        )

    assert called == []


def test_no_pending_orders_does_not_collect(
    tmp_path,
    monkeypatch,
):
    _, _, _ = configure(tmp_path, monkeypatch)

    called = []

    result = collect_and_check_model2(
        SESSION,
        clock=clock_sequence(START),
        pending_query_factory=lambda path: (
            FakePendingQuery([])
        ),
        collector_factory=lambda storage: (
            called.append(storage)
        ),
    )

    assert result.pending_order_count == 0
    assert result.ready_order_count == 0
    assert result.collection is None
    assert result.eligibility is None
    assert called == []