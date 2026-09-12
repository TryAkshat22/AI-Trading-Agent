from __future__ import annotations

from datetime import (
    date,
    datetime,
    timezone,
)

import pytest

from trading.decision_timestamp import (
    DecisionAfterExecutionOpenError,
    DecisionBeforeCloseError,
    DecisionTimestampValidator,
    InvalidSourceSessionError,
    NaiveDecisionTimestampError,
)


def make_validator(
) -> DecisionTimestampValidator:

    return DecisionTimestampValidator(
        calendar_name="NYSE"
    )


def test_after_close_decision_is_valid():

    validator = make_validator()

    result = validator.validate(
        source_session=date(
            2026,
            9,
            4,
        ),
        decision_timestamp=datetime(
            2026,
            9,
            4,
            21,
            0,
            tzinfo=timezone.utc,
        ),
    )

    assert (
        result.source_session
        == date(
            2026,
            9,
            4,
        )
    )

    # Labor Day 2026 is Monday,
    # September 7, so next NYSE session
    # should be Tuesday, September 8.
    assert (
        result.next_execution_session
        == date(
            2026,
            9,
            8,
        )
    )

    assert (
        result.decision_timestamp_utc
        >= result.source_close_utc
    )

    assert (
        result.decision_timestamp_utc
        < result.next_execution_open_utc
    )


def test_decision_before_close_is_rejected():

    validator = make_validator()

    with pytest.raises(
        DecisionBeforeCloseError
    ):
        validator.validate(
            source_session=date(
                2026,
                9,
                4,
            ),

            # 18:00 UTC = 2 PM New York
            # during daylight saving time.
            decision_timestamp=datetime(
                2026,
                9,
                4,
                18,
                0,
                tzinfo=timezone.utc,
            ),
        )


def test_decision_at_next_open_is_rejected():

    validator = make_validator()

    # Tuesday, September 8, 2026
    # NYSE regular open is 13:30 UTC.
    with pytest.raises(
        DecisionAfterExecutionOpenError
    ):
        validator.validate(
            source_session=date(
                2026,
                9,
                4,
            ),
            decision_timestamp=datetime(
                2026,
                9,
                8,
                13,
                30,
                tzinfo=timezone.utc,
            ),
        )


def test_weekend_source_session_is_rejected():

    validator = make_validator()

    with pytest.raises(
        InvalidSourceSessionError
    ):
        validator.validate(
            source_session=date(
                2026,
                9,
                5,
            ),
            decision_timestamp=datetime(
                2026,
                9,
                5,
                21,
                0,
                tzinfo=timezone.utc,
            ),
        )


def test_holiday_source_session_is_rejected():

    validator = make_validator()

    # Labor Day 2026.
    with pytest.raises(
        InvalidSourceSessionError
    ):
        validator.validate(
            source_session=date(
                2026,
                9,
                7,
            ),
            decision_timestamp=datetime(
                2026,
                9,
                7,
                21,
                0,
                tzinfo=timezone.utc,
            ),
        )


def test_naive_decision_timestamp_is_rejected():

    validator = make_validator()

    with pytest.raises(
        NaiveDecisionTimestampError
    ):
        validator.validate(
            source_session=date(
                2026,
                9,
                4,
            ),
            decision_timestamp=datetime(
                2026,
                9,
                4,
                21,
                0,
            ),
        )


def test_exact_source_close_is_allowed():

    validator = make_validator()

    # September 4, 2026 regular NYSE close:
    # 20:00 UTC.
    result = validator.validate(
        source_session=date(
            2026,
            9,
            4,
        ),
        decision_timestamp=datetime(
            2026,
            9,
            4,
            20,
            0,
            tzinfo=timezone.utc,
        ),
    )

    assert (
        result.decision_timestamp_utc
        == result.source_close_utc
    )


def test_one_second_before_next_open_is_allowed():

    validator = make_validator()

    result = validator.validate(
        source_session=date(
            2026,
            9,
            4,
        ),
        decision_timestamp=datetime(
            2026,
            9,
            8,
            13,
            29,
            59,
            tzinfo=timezone.utc,
        ),
    )

    assert (
        result.decision_timestamp_utc
        < result.next_execution_open_utc
    )