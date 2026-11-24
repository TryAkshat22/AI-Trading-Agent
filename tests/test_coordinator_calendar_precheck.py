
from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest

from trading.decision_execution_coordinator import (
    DecisionExecutionCoordinator,
    DecisionExecutionCoordinatorError,
)
from trading.decision_pipeline import DecisionStatus
from trading.orders import OrderSide


SOURCE_SESSION = date(2026, 9, 15)
EXPECTED_SESSION = date(2026, 9, 16)
WRONG_SESSION = date(2026, 9, 17)

DECISION_TIME = datetime(
    2026, 9, 15, 21, 0, tzinfo=timezone.utc
)


class FakeTimestampValidator:
    def validate(self, source_session, decision_timestamp):
        assert source_session == SOURCE_SESSION

        return SimpleNamespace(
            decision_timestamp_utc=decision_timestamp,
            next_execution_session=EXPECTED_SESSION,
        )


class FakeScheduler:
    def __init__(self, execution_session):
        self.execution_session = execution_session
        self.calls = 0

    def create_plan(self, signal_timestamp):
        self.calls += 1
        assert signal_timestamp == DECISION_TIME

        return SimpleNamespace(
            execution_session=self.execution_session,
        )


class FakeExecutionService:
    def __init__(self, execution_session):
        self.scheduler = FakeScheduler(execution_session)
        self.prepared = []

    def prepare_order(self, **kwargs):
        self.prepared.append(kwargs)

        return SimpleNamespace(
            execution_plan=SimpleNamespace(
                execution_session=self.scheduler.execution_session
            )
        )


def approved_decision():
    return SimpleNamespace(
        status=DecisionStatus.BUY_APPROVED,
        side=OrderSide.BUY,
        quantity=2,
        signal=SimpleNamespace(
            ticker="AAPL",
            source_session=SOURCE_SESSION,
        ),
    )


def make_coordinator(execution_session):
    service = FakeExecutionService(execution_session)

    coordinator = DecisionExecutionCoordinator(
        execution_service=service,
        timestamp_validator=FakeTimestampValidator(),
    )

    return coordinator, service


def test_calendar_disagreement_prevents_order_preparation():
    coordinator, service = make_coordinator(
        WRONG_SESSION
    )

    with pytest.raises(
        DecisionExecutionCoordinatorError,
        match="No order was prepared",
    ):
        coordinator.coordinate(
            decision=approved_decision(),
            decision_timestamp=DECISION_TIME,
            decision_run_id="decision-run-1",
            model_version="model-2-flexible",
            order_id="model-2-flexible-2026-09-15-AAPL",
        )

    assert service.scheduler.calls == 1
    assert service.prepared == []


def test_calendar_agreement_allows_order_preparation():
    coordinator, service = make_coordinator(
        EXPECTED_SESSION
    )

    result = coordinator.coordinate(
        decision=approved_decision(),
        decision_timestamp=DECISION_TIME,
        decision_run_id="decision-run-1",
        model_version="model-2-flexible",
        order_id="model-2-flexible-2026-09-15-AAPL",
    )

    assert result.order_created
    assert service.scheduler.calls == 1
    assert len(service.prepared) == 1

    prepared_arguments = service.prepared[0]

    assert prepared_arguments["model_version"] == (
        "model-2-flexible"
    )
    assert prepared_arguments["decision_run_id"] == (
        "decision-run-1"
    )
    assert prepared_arguments["order_id"] == (
        "model-2-flexible-2026-09-15-AAPL"
    )


def test_non_actionable_decision_never_prepares_order():
    coordinator, service = make_coordinator(
        EXPECTED_SESSION
    )

    decision = SimpleNamespace(
        status=DecisionStatus.HOLD,
    )

    result = coordinator.coordinate(
        decision=decision,
        decision_timestamp=DECISION_TIME,
        decision_run_id=None,
        model_version=None,
    )

    assert not result.order_created
    assert service.scheduler.calls == 0
    assert service.prepared == []


def test_missing_decision_lineage_does_not_prepare_order():
    coordinator, service = make_coordinator(
        EXPECTED_SESSION
    )

    with pytest.raises(Exception):
        coordinator.coordinate(
            decision=approved_decision(),
            decision_timestamp=DECISION_TIME,
            decision_run_id=None,
            model_version="model-2-flexible",
        )

    assert service.scheduler.calls == 0
    assert service.prepared == []