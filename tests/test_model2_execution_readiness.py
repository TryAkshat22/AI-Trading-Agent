
from datetime import date, datetime, timezone

import pytest

from model2_execution_readiness import (
    Model2ExecutionReadinessError,
    check_execution_window,
)


SESSION = date(2026, 9, 18)


def at_utc(hour, minute):
    return datetime(
        2026, 9, 18,
        hour, minute,
        tzinfo=timezone.utc,
    )


def test_window_opens_at_945_et():
    check_execution_window(
        SESSION,
        at_utc(13, 45),
    )


def test_window_allows_1000_et():
    check_execution_window(
        SESSION,
        at_utc(14, 0),
    )


def test_before_window_is_blocked():
    with pytest.raises(
        Model2ExecutionReadinessError,
        match="Outside",
    ):
        check_execution_window(
            SESSION,
            at_utc(13, 44),
        )


def test_1530_et_is_too_late():
    with pytest.raises(
        Model2ExecutionReadinessError,
        match="Outside",
    ):
        check_execution_window(
            SESSION,
            at_utc(19, 30),
        )


def test_previous_session_is_blocked():
    with pytest.raises(
        Model2ExecutionReadinessError,
        match="today's New York calendar date",
    ):
        check_execution_window(
            date(2026, 9, 17),
            at_utc(14, 0),
        )


def test_weekend_is_blocked():
    with pytest.raises(
        Model2ExecutionReadinessError,
        match="not an NYSE session",
    ):
        check_execution_window(
            date(2026, 9, 19),
            datetime(
                2026, 9, 19, 14, 0,
                tzinfo=timezone.utc,
            ),
        )


def test_naive_time_is_blocked():
    with pytest.raises(
        Model2ExecutionReadinessError,
        match="timezone-aware",
    ):
        check_execution_window(
            SESSION,
            datetime(2026, 9, 18, 14, 0),
        )