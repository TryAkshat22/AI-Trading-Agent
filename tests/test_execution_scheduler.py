from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from trading.execution_scheduler import (
    ExecutionScheduler,
    IntradaySignalError,
    InvalidSignalTimestampError,
)


def test_normal_after_close_signal():

    scheduler = ExecutionScheduler()

    # Thursday Sep 3, 2026
    # signal generated after NYSE close
    signal = datetime(
        2026,
        9,
        3,
        21,
        0,
        tzinfo=timezone.utc,
    )

    plan = scheduler.create_plan(
        signal
    )

    assert (
        plan.source_session.isoformat()
        == "2026-09-03"
    )

    assert (
        plan.execution_session.isoformat()
        == "2026-09-04"
    )


def test_labor_day_weekend_is_skipped():

    scheduler = ExecutionScheduler()

    # Friday Sep 4, 2026 after close.
    #
    # Sep 5 = Saturday
    # Sep 6 = Sunday
    # Sep 7 = Labor Day
    # Sep 8 = next NYSE session
    signal = datetime(
        2026,
        9,
        4,
        21,
        0,
        tzinfo=timezone.utc,
    )

    plan = scheduler.create_plan(
        signal
    )

    assert (
        plan.source_session.isoformat()
        == "2026-09-04"
    )

    assert (
        plan.execution_session.isoformat()
        == "2026-09-08"
    )


def test_weekend_signal_uses_previous_session():

    scheduler = ExecutionScheduler()

    # Sunday Sep 6
    signal = datetime(
        2026,
        9,
        6,
        18,
        0,
        tzinfo=timezone.utc,
    )

    plan = scheduler.create_plan(
        signal
    )

    assert (
        plan.source_session.isoformat()
        == "2026-09-04"
    )

    assert (
        plan.execution_session.isoformat()
        == "2026-09-08"
    )


def test_holiday_signal_uses_previous_session():

    scheduler = ExecutionScheduler()

    # Monday Sep 7 = Labor Day
    signal = datetime(
        2026,
        9,
        7,
        18,
        0,
        tzinfo=timezone.utc,
    )

    plan = scheduler.create_plan(
        signal
    )

    assert (
        plan.source_session.isoformat()
        == "2026-09-04"
    )

    assert (
        plan.execution_session.isoformat()
        == "2026-09-08"
    )


def test_premarket_signal_can_execute_at_open():

    scheduler = ExecutionScheduler()

    # Tuesday Sep 8 at 8:00 AM ET.
    #
    # Market has not opened yet.
    eastern = ZoneInfo(
        "America/New_York"
    )

    signal = datetime(
        2026,
        9,
        8,
        8,
        0,
        tzinfo=eastern,
    )

    plan = scheduler.create_plan(
        signal
    )

    assert (
        plan.source_session.isoformat()
        == "2026-09-04"
    )

    assert (
        plan.execution_session.isoformat()
        == "2026-09-08"
    )


def test_intraday_signal_is_rejected():

    scheduler = ExecutionScheduler()

    eastern = ZoneInfo(
        "America/New_York"
    )

    # Tuesday Sep 8 at 10 AM ET,
    # after the market has already opened.
    signal = datetime(
        2026,
        9,
        8,
        10,
        0,
        tzinfo=eastern,
    )

    with pytest.raises(
        IntradaySignalError
    ):
        scheduler.create_plan(
            signal
        )


def test_naive_timestamp_is_rejected():

    scheduler = ExecutionScheduler()

    signal = datetime(
        2026,
        9,
        4,
        21,
        0,
    )

    with pytest.raises(
        InvalidSignalTimestampError
    ):
        scheduler.create_plan(
            signal
        )


def test_non_utc_timezone_is_normalized():

    scheduler = ExecutionScheduler()

    eastern = ZoneInfo(
        "America/New_York"
    )

    signal = datetime(
        2026,
        9,
        4,
        17,
        0,
        tzinfo=eastern,
    )

    plan = scheduler.create_plan(
        signal
    )

    assert (
        plan.signal_timestamp_utc
        .tzinfo
        == timezone.utc
    )

    assert (
        plan.signal_timestamp_utc.hour
        == 21
    )


def test_execution_open_occurs_after_signal():

    scheduler = ExecutionScheduler()

    signal = datetime(
        2026,
        9,
        4,
        21,
        0,
        tzinfo=timezone.utc,
    )

    plan = scheduler.create_plan(
        signal
    )

    assert (
        plan.execution_open_utc
        > plan.signal_timestamp_utc
    )