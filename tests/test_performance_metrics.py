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
from evaluation.performance_metrics import (
    PerformanceMetricError,
    PerformanceMetricService,
)


def snapshot(
    session: date,
    equity: str,
):

    equity_value = Decimal(
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
        market_value=(
            equity_value
        ),
        total_equity=(
            equity_value
        ),
        realized_pnl=Decimal(
            "0"
        ),
        unrealized_pnl=Decimal(
            "0"
        ),
        total_pnl=(
            equity_value
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
        PerformanceMetricService()
    )

    with pytest.raises(
        PerformanceMetricError
    ):

        service.calculate(
            []
        )


def test_single_snapshot():

    service = (
        PerformanceMetricService()
    )

    metrics = (
        service.calculate(
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
        metrics.observations
        == 1
    )

    assert (
        metrics.total_return_pct
        == Decimal(
            "0"
        )
    )

    assert (
        metrics.sharpe_ratio
        is None
    )

    assert (
        metrics.sortino_ratio
        is None
    )


def test_total_return():

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
            "10500",
        ),
    ]

    metrics = (
        PerformanceMetricService()
        .calculate(
            history
        )
    )

    assert (
        metrics.total_return_pct
        == Decimal(
            "5.00"
        )
    )


def test_max_drawdown():

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
            "11000",
        ),
        snapshot(
            date(
                2026,
                9,
                16,
            ),
            "8800",
        ),
    ]

    metrics = (
        PerformanceMetricService()
        .calculate(
            history
        )
    )

    assert (
        metrics.max_drawdown_pct
        == Decimal(
            "20.0"
        )
    )


def test_positive_negative_day_rates():

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
            "10100",
        ),
        snapshot(
            date(
                2026,
                9,
                16,
            ),
            "9999",
        ),
    ]

    metrics = (
        PerformanceMetricService()
        .calculate(
            history
        )
    )

    assert (
        metrics.positive_day_rate_pct
        == Decimal(
            "50.0"
        )
    )

    assert (
        metrics.negative_day_rate_pct
        == Decimal(
            "50.0"
        )
    )


def test_best_and_worst_day():

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
            "11000",
        ),
        snapshot(
            date(
                2026,
                9,
                16,
            ),
            "9900",
        ),
    ]

    metrics = (
        PerformanceMetricService()
        .calculate(
            history
        )
    )

    assert (
        metrics.best_day_pct
        == Decimal(
            "10.0"
        )
    )

    assert (
        metrics.worst_day_pct
        == Decimal(
            "-10.0"
        )
    )


def test_flat_returns_have_no_sharpe():

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
            "10000",
        ),
        snapshot(
            date(
                2026,
                9,
                16,
            ),
            "10000",
        ),
    ]

    metrics = (
        PerformanceMetricService()
        .calculate(
            history
        )
    )

    assert (
        metrics.sharpe_ratio
        is None
    )


def test_all_positive_returns_have_no_sortino():

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

    metrics = (
        PerformanceMetricService()
        .calculate(
            history
        )
    )

    assert (
        metrics.sortino_ratio
        is None
    )


def test_variable_returns_produce_sharpe():

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
            "10100",
        ),
        snapshot(
            date(
                2026,
                9,
                16,
            ),
            "9999",
        ),
        snapshot(
            date(
                2026,
                9,
                17,
            ),
            "10200",
        ),
    ]

    metrics = (
        PerformanceMetricService()
        .calculate(
            history
        )
    )

    assert (
        metrics.sharpe_ratio
        is not None
    )

    assert (
        metrics.annualized_volatility_pct
        > 0
    )


def test_negative_equity_rejected():

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
            "-1",
        ),
    ]

    with pytest.raises(
        PerformanceMetricError
    ):

        PerformanceMetricService().calculate(
            history
        )

def test_history_sorted_before_metrics():

    history = [
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

    metrics = (
        PerformanceMetricService()
        .calculate(
            history
        )
    )

    assert (
        metrics.total_return_pct
        == Decimal(
            "2.00"
        )
    )