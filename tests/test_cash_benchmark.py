from datetime import (
    date,
    datetime,
    timezone,
)
from decimal import Decimal

import pytest

from database.equity_storage import (
    EquitySnapshot,
)
from evaluation.cash_benchmark import (
    CashBenchmarkError,
    CashBenchmarkService,
)


def snapshot(
    session: date,
    equity: str,
):

    value = Decimal(
        equity
    )

    return EquitySnapshot(
        snapshot_id=(
            f"snapshot-{session}"
        ),
        account_id="model1-paper",
        model_version="model-1",
        valuation_session=session,
        starting_cash=Decimal(
            "10000"
        ),
        cash=Decimal(
            "0"
        ),
        market_value=value,
        total_equity=value,
        realized_pnl=Decimal(
            "0"
        ),
        unrealized_pnl=Decimal(
            "0"
        ),
        total_pnl=(
            value
            - Decimal(
                "10000"
            )
        ),
        total_return_pct=Decimal(
            "0"
        ),
        exposure_pct=Decimal(
            "100"
        ),
        open_positions=1,
        recorded_at_utc=datetime(
            2026,
            9,
            14,
            20,
            0,
            tzinfo=timezone.utc,
        ),
    )


def test_empty_history_rejected():

    service = (
        CashBenchmarkService()
    )

    with pytest.raises(
        CashBenchmarkError
    ):

        service.compare(
            []
        )


def test_single_snapshot_zero_returns():

    comparison = (
        CashBenchmarkService()
        .compare(
            [
                snapshot(
                    date(
                        2026,
                        9,
                        14,
                    ),
                    "10000",
                )
            ]
        )
    )

    assert (
        comparison.model_total_return_pct
        == Decimal(
            "0"
        )
    )

    assert (
        comparison.cash_total_return_pct
        == Decimal(
            "0"
        )
    )

    assert (
        comparison.excess_return_pct
        == Decimal(
            "0"
        )
    )


def test_positive_model_return_beats_cash():

    comparison = (
        CashBenchmarkService()
        .compare(
            [
                snapshot(
                    date(
                        2026,
                        9,
                        14,
                    ),
                    "10000",
                ),
                snapshot(
                    date(
                        2026,
                        9,
                        15,
                    ),
                    "10500",
                ),
            ]
        )
    )

    assert (
        comparison.model_total_return_pct
        == Decimal(
            "5.00"
        )
    )

    assert (
        comparison.cash_total_return_pct
        == Decimal(
            "0"
        )
    )

    assert (
        comparison.excess_return_pct
        == Decimal(
            "5.00"
        )
    )


def test_negative_model_return_loses_to_cash():

    comparison = (
        CashBenchmarkService()
        .compare(
            [
                snapshot(
                    date(
                        2026,
                        9,
                        14,
                    ),
                    "10000",
                ),
                snapshot(
                    date(
                        2026,
                        9,
                        15,
                    ),
                    "9500",
                ),
            ]
        )
    )

    assert (
        comparison.model_total_return_pct
        == Decimal(
            "-5.00"
        )
    )

    assert (
        comparison.excess_return_pct
        == Decimal(
            "-5.00"
        )
    )


def test_cash_value_remains_constant():

    comparison = (
        CashBenchmarkService()
        .compare(
            [
                snapshot(
                    date(
                        2026,
                        9,
                        14,
                    ),
                    "10000",
                ),
                snapshot(
                    date(
                        2026,
                        9,
                        15,
                    ),
                    "10100",
                ),
                snapshot(
                    date(
                        2026,
                        9,
                        16,
                    ),
                    "10200",
                ),
            ]
        )
    )

    assert all(
        point.cash_value
        == Decimal(
            "10000"
        )
        for point
        in comparison.points
    )


def test_history_sorted_by_session():

    comparison = (
        CashBenchmarkService()
        .compare(
            [
                snapshot(
                    date(
                        2026,
                        9,
                        16,
                    ),
                    "10200",
                ),
                snapshot(
                    date(
                        2026,
                        9,
                        14,
                    ),
                    "10000",
                ),
                snapshot(
                    date(
                        2026,
                        9,
                        15,
                    ),
                    "10100",
                ),
            ]
        )
    )

    assert [
        point.session
        for point
        in comparison.points
    ] == [
        date(
            2026,
            9,
            14,
        ),
        date(
            2026,
            9,
            15,
        ),
        date(
            2026,
            9,
            16,
        ),
    ]


def test_point_excess_return_matches_model_return():

    comparison = (
        CashBenchmarkService()
        .compare(
            [
                snapshot(
                    date(
                        2026,
                        9,
                        14,
                    ),
                    "10000",
                ),
                snapshot(
                    date(
                        2026,
                        9,
                        15,
                    ),
                    "10250",
                ),
            ]
        )
    )

    point = (
        comparison.points[
            1
        ]
    )

    assert (
        point.model_return_pct
        == Decimal(
            "2.500"
        )
    )

    assert (
        point.excess_return_pct
        == point.model_return_pct
    )


def test_nonpositive_equity_rejected():

    history = [
        snapshot(
            date(
                2026,
                9,
                14,
            ),
            "10000",
        ),
        snapshot(
            date(
                2026,
                9,
                15,
            ),
            "0",
        ),
    ]

    with pytest.raises(
        CashBenchmarkError
    ):

        CashBenchmarkService().compare(
            history
        )