from __future__ import annotations

from datetime import (
    date,
    datetime,
    timezone,
)
from types import SimpleNamespace

import pytest

from trading.decision_execution_coordinator import (
    DecisionExecutionCoordinator,
    InvalidApprovedDecisionError,
    MissingDecisionRunIdError,
    MissingDecisionSourceSessionError,
    MissingModelVersionError,
)
from trading.decision_pipeline import (
    DecisionStatus,
)
from trading.orders import (
    OrderSide,
)


class FakeExecutionPlan:
    def __init__(
        self,
        execution_session,
    ):

        self.execution_session = (
            execution_session
        )


class FakePreparedOrder:
    def __init__(
        self,
        execution_session,
    ):

        self.execution_plan = (
            FakeExecutionPlan(
                execution_session
            )
        )

        self.order = SimpleNamespace(
            order_id="test-order"
        )


class FakeExecutionService:
    def __init__(self):

        self.calls = []

    def prepare_order(
        self,
        **kwargs,
    ):

        self.calls.append(
            kwargs
        )

        return FakePreparedOrder(
            execution_session=date(
                2026,
                9,
                8,
            )
        )


def make_decision(
    status,
    side=None,
    quantity=None,
    source_session=date(
        2026,
        9,
        4,
    ),
):

    signal = SimpleNamespace(
        ticker="AAPL",
        source_session=(
            source_session
        ),
    )

    return SimpleNamespace(
        status=status,
        signal=signal,
        side=side,
        quantity=quantity,
    )


def valid_timestamp():

    return datetime(
        2026,
        9,
        4,
        21,
        0,
        tzinfo=timezone.utc,
    )


def test_buy_approved_creates_order():

    execution_service = (
        FakeExecutionService()
    )

    coordinator = (
        DecisionExecutionCoordinator(
            execution_service=(
                execution_service
            )
        )
    )

    decision = make_decision(
        status=(
            DecisionStatus
            .BUY_APPROVED
        ),
        side=OrderSide.BUY,
        quantity=5,
    )

    result = coordinator.coordinate(
        decision=decision,
        decision_timestamp=(
            valid_timestamp()
        ),
        decision_run_id=(
            "decision-run-1"
        ),
        model_version="model-1",
        order_id="order-1",
    )

    assert result.order_created

    assert (
        len(
            execution_service.calls
        )
        == 1
    )

    call = (
        execution_service.calls[0]
    )

    assert (
        call["ticker"]
        == "AAPL"
    )

    assert (
        call["side"]
        == OrderSide.BUY
    )

    assert (
        call["quantity"]
        == 5
    )

    assert (
        call["decision_run_id"]
        == "decision-run-1"
    )

    assert (
        call["model_version"]
        == "model-1"
    )

    assert (
        call["order_id"]
        == "order-1"
    )


def test_exit_approved_creates_sell_order():

    execution_service = (
        FakeExecutionService()
    )

    coordinator = (
        DecisionExecutionCoordinator(
            execution_service=(
                execution_service
            )
        )
    )

    decision = make_decision(
        status=(
            DecisionStatus
            .EXIT_APPROVED
        ),
        side=OrderSide.SELL,
        quantity=7,
    )

    result = coordinator.coordinate(
        decision=decision,
        decision_timestamp=(
            valid_timestamp()
        ),
        decision_run_id=(
            "decision-run-1"
        ),
        model_version="model-1",
    )

    assert result.order_created

    assert (
        execution_service
        .calls[0]["side"]
        == OrderSide.SELL
    )

    assert (
        execution_service
        .calls[0]["quantity"]
        == 7
    )


@pytest.mark.parametrize(
    "status",
    [
        DecisionStatus.HOLD,
        DecisionStatus.NO_TRADE,
        DecisionStatus.SIZE_ZERO,
        DecisionStatus.RISK_REJECTED,
    ],
)
def test_non_actionable_decision_creates_no_order(
    status,
):

    execution_service = (
        FakeExecutionService()
    )

    coordinator = (
        DecisionExecutionCoordinator(
            execution_service=(
                execution_service
            )
        )
    )

    decision = make_decision(
        status=status,
    )

    result = coordinator.coordinate(
        decision=decision,

        # These values should not matter for a
        # non-actionable decision.
        decision_timestamp=(
            valid_timestamp()
        ),
        decision_run_id=None,
        model_version=None,
    )

    assert not result.order_created

    assert (
        result.prepared_order
        is None
    )

    assert (
        result.validated_timestamp
        is None
    )

    assert (
        execution_service.calls
        == []
    )


def test_missing_source_session_fails():

    coordinator = (
        DecisionExecutionCoordinator(
            execution_service=(
                FakeExecutionService()
            )
        )
    )

    decision = make_decision(
        status=(
            DecisionStatus
            .BUY_APPROVED
        ),
        side=OrderSide.BUY,
        quantity=5,
        source_session=None,
    )

    with pytest.raises(
        MissingDecisionSourceSessionError
    ):
        coordinator.coordinate(
            decision=decision,
            decision_timestamp=(
                valid_timestamp()
            ),
            decision_run_id=(
                "decision-run-1"
            ),
            model_version="model-1",
        )


def test_missing_decision_run_id_fails():

    coordinator = (
        DecisionExecutionCoordinator(
            execution_service=(
                FakeExecutionService()
            )
        )
    )

    decision = make_decision(
        status=(
            DecisionStatus
            .BUY_APPROVED
        ),
        side=OrderSide.BUY,
        quantity=5,
    )

    with pytest.raises(
        MissingDecisionRunIdError
    ):
        coordinator.coordinate(
            decision=decision,
            decision_timestamp=(
                valid_timestamp()
            ),
            decision_run_id=None,
            model_version="model-1",
        )


def test_missing_model_version_fails():

    coordinator = (
        DecisionExecutionCoordinator(
            execution_service=(
                FakeExecutionService()
            )
        )
    )

    decision = make_decision(
        status=(
            DecisionStatus
            .BUY_APPROVED
        ),
        side=OrderSide.BUY,
        quantity=5,
    )

    with pytest.raises(
        MissingModelVersionError
    ):
        coordinator.coordinate(
            decision=decision,
            decision_timestamp=(
                valid_timestamp()
            ),
            decision_run_id=(
                "decision-run-1"
            ),
            model_version=None,
        )


def test_buy_status_with_sell_side_fails():

    coordinator = (
        DecisionExecutionCoordinator(
            execution_service=(
                FakeExecutionService()
            )
        )
    )

    decision = make_decision(
        status=(
            DecisionStatus
            .BUY_APPROVED
        ),
        side=OrderSide.SELL,
        quantity=5,
    )

    with pytest.raises(
        InvalidApprovedDecisionError
    ):
        coordinator.coordinate(
            decision=decision,
            decision_timestamp=(
                valid_timestamp()
            ),
            decision_run_id=(
                "decision-run-1"
            ),
            model_version="model-1",
        )


def test_exit_status_with_buy_side_fails():

    coordinator = (
        DecisionExecutionCoordinator(
            execution_service=(
                FakeExecutionService()
            )
        )
    )

    decision = make_decision(
        status=(
            DecisionStatus
            .EXIT_APPROVED
        ),
        side=OrderSide.BUY,
        quantity=5,
    )

    with pytest.raises(
        InvalidApprovedDecisionError
    ):
        coordinator.coordinate(
            decision=decision,
            decision_timestamp=(
                valid_timestamp()
            ),
            decision_run_id=(
                "decision-run-1"
            ),
            model_version="model-1",
        )


def test_zero_quantity_fails():

    coordinator = (
        DecisionExecutionCoordinator(
            execution_service=(
                FakeExecutionService()
            )
        )
    )

    decision = make_decision(
        status=(
            DecisionStatus
            .BUY_APPROVED
        ),
        side=OrderSide.BUY,
        quantity=0,
    )

    with pytest.raises(
        InvalidApprovedDecisionError
    ):
        coordinator.coordinate(
            decision=decision,
            decision_timestamp=(
                valid_timestamp()
            ),
            decision_run_id=(
                "decision-run-1"
            ),
            model_version="model-1",
        )