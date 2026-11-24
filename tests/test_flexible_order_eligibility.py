
from dataclasses import replace
from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest

from audit_pending_orders import (
    PendingOrderAuditRecord,
    PendingOrderAuditResult,
)
from database.pending_order_query import PendingOrderReference
from trading.flexible_order_eligibility import (
    FlexibleOrderEligibilityChecker,
    FlexibleOrderEligibilityError,
)


SESSION = date(2026, 9, 16)

CHECKED = datetime(
    2026, 9, 16, 14, 2,
    tzinfo=timezone.utc,
)


def reference(
    order_id="order-1",
    ticker="AAPL",
    model_version="model-2-flexible",
):
    return PendingOrderReference(
        order_id=order_id,
        ticker=ticker,
        execution_session=SESSION,
        model_version=model_version,
    )


def audit_record(
    order_id="order-1",
    ticker="AAPL",
    model_version="model-2-flexible",
    **changes,
):
    values = {
        "order_id": order_id,
        "ticker": ticker,
        "side": "BUY",
        "quantity": 1,
        "status": "PENDING",
        "execution_session": SESSION,
        "model_version": model_version,
        "decision_run_id": "decision-1",
        "fill_count": 0,
        "execution_attempt_count": 0,
    }

    values.update(changes)

    return PendingOrderAuditRecord(**values)


class FakeQuery:
    def __init__(self, references):
        self.references = tuple(references)

    def find_for_session(self, execution_session):
        return self.references


class FakeAuditor:
    def __init__(self, records):
        self.records = tuple(records)

    def audit_session(self, execution_session):
        return PendingOrderAuditResult(
            execution_session=execution_session,
            records=self.records,
        )


class FakeSelector:
    def __init__(self, error=None):
        self.error = error
        self.calls = 0

    def select(
        self,
        ticker,
        execution_session,
        checked_at,
    ):
        self.calls += 1

        if self.error is not None:
            raise self.error

        return SimpleNamespace(
            reference_price=101.0,
            price_field="Close",
            retrieved_at_utc=datetime(
                2026, 9, 16, 14, 1, 10,
                tzinfo=timezone.utc,
            ),
            bar_start_utc=datetime(
                2026, 9, 16, 14, 0,
                tzinfo=timezone.utc,
            ),
        )


def make_checker(
    references=None,
    records=None,
    selector=None,
):
    if references is None:
        references = [reference()]

    if records is None:
        records = [audit_record()]

    if selector is None:
        selector = FakeSelector()

    checker = FlexibleOrderEligibilityChecker(
        pending_order_query=FakeQuery(references),
        auditor=FakeAuditor(records),
        observation_selector=selector,
    )

    return checker, selector


def test_clean_model_2_order_is_eligible():
    checker, selector = make_checker()

    result = checker.check(SESSION, CHECKED)

    assert result.eligible_count == 1
    assert result.ineligible_count == 0
    assert result.eligible_orders[0].reference_price == 101.0
    assert selector.calls == 1


def test_original_model_order_is_not_eligible():
    checker, selector = make_checker(
        references=[
            reference(model_version="model-1")
        ],
        records=[
            audit_record(model_version="model-1")
        ],
    )

    result = checker.check(SESSION, CHECKED)

    assert result.eligible_count == 0
    assert result.ineligible_count == 1
    assert selector.calls == 0


def test_existing_attempt_blocks_eligibility():
    checker, selector = make_checker(
        records=[
            audit_record(
                execution_attempt_count=1
            )
        ],
    )

    result = checker.check(SESSION, CHECKED)

    assert result.eligible_count == 0
    assert result.ineligible_count == 1
    assert selector.calls == 0


def test_existing_fill_blocks_eligibility():
    checker, selector = make_checker(
        records=[
            audit_record(fill_count=1)
        ],
    )

    result = checker.check(SESSION, CHECKED)

    assert result.eligible_count == 0
    assert selector.calls == 0


def test_missing_observation_does_not_reject_order():
    checker, selector = make_checker(
        selector=FakeSelector(
            error=RuntimeError("No fresh bar.")
        )
    )

    result = checker.check(SESSION, CHECKED)

    assert result.eligible_count == 0
    assert result.ineligible_count == 1
    assert "No eligible price observation" in (
        result.ineligible_orders[0].reason
    )


def test_discovery_audit_mismatch_fails_closed():
    checker, _ = make_checker(
        references=[reference()],
        records=[
            audit_record(order_id="different-order")
        ],
    )

    with pytest.raises(
        FlexibleOrderEligibilityError
    ):
        checker.check(SESSION, CHECKED)


def test_ticker_mismatch_fails_closed():
    checker, _ = make_checker(
        records=[
            audit_record(ticker="MSFT")
        ],
    )

    with pytest.raises(
        FlexibleOrderEligibilityError
    ):
        checker.check(SESSION, CHECKED)


def test_naive_check_time_rejected():
    checker, _ = make_checker()

    with pytest.raises(
        FlexibleOrderEligibilityError
    ):
        checker.check(
            SESSION,
            datetime(2026, 9, 16, 14, 2),
        )