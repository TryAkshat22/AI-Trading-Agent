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
from evaluation.benchmark import (
    BenchmarkComparison,
    BenchmarkComparisonPoint,
)
from evaluation.equal_weight_benchmark import (
    EqualWeightBenchmarkComparison,
    EqualWeightBenchmarkPoint,
)
from evaluation.report_charts import (
    ReportChartError,
    ReportChartService,
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
        cash=value,
        market_value=Decimal(
            "0"
        ),
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
            "0"
        ),
        open_positions=0,
        recorded_at_utc=datetime(
            2026,
            9,
            14,
            20,
            0,
            tzinfo=timezone.utc,
        ),
    )


def spy_comparison():

    return BenchmarkComparison(
        symbol="SPY",
        starting_model_equity=Decimal(
            "10000"
        ),
        starting_benchmark_price=Decimal(
            "500"
        ),
        ending_model_equity=Decimal(
            "10200"
        ),
        ending_benchmark_price=Decimal(
            "505"
        ),
        model_total_return_pct=Decimal(
            "2"
        ),
        benchmark_total_return_pct=Decimal(
            "1"
        ),
        excess_return_pct=Decimal(
            "1"
        ),
        points=(
            BenchmarkComparisonPoint(
                session=date(
                    2026,
                    9,
                    14,
                ),
                model_equity=Decimal(
                    "10000"
                ),
                model_return_pct=Decimal(
                    "0"
                ),
                benchmark_price=Decimal(
                    "500"
                ),
                benchmark_return_pct=Decimal(
                    "0"
                ),
                excess_return_pct=Decimal(
                    "0"
                ),
            ),
            BenchmarkComparisonPoint(
                session=date(
                    2026,
                    9,
                    15,
                ),
                model_equity=Decimal(
                    "10200"
                ),
                model_return_pct=Decimal(
                    "2"
                ),
                benchmark_price=Decimal(
                    "505"
                ),
                benchmark_return_pct=Decimal(
                    "1"
                ),
                excess_return_pct=Decimal(
                    "1"
                ),
            ),
        ),
    )


def equal_weight_comparison():

    return EqualWeightBenchmarkComparison(
        symbols=(
            "AAPL",
            "MSFT",
        ),
        starting_equity=Decimal(
            "10000"
        ),
        ending_equity=Decimal(
            "10200"
        ),
        starting_benchmark_value=Decimal(
            "10000"
        ),
        ending_benchmark_value=Decimal(
            "10150"
        ),
        model_total_return_pct=Decimal(
            "2"
        ),
        benchmark_total_return_pct=Decimal(
            "1.5"
        ),
        excess_return_pct=Decimal(
            "0.5"
        ),
        points=(
            EqualWeightBenchmarkPoint(
                session=date(
                    2026,
                    9,
                    14,
                ),
                model_equity=Decimal(
                    "10000"
                ),
                benchmark_value=Decimal(
                    "10000"
                ),
                model_return_pct=Decimal(
                    "0"
                ),
                benchmark_return_pct=Decimal(
                    "0"
                ),
                excess_return_pct=Decimal(
                    "0"
                ),
            ),
            EqualWeightBenchmarkPoint(
                session=date(
                    2026,
                    9,
                    15,
                ),
                model_equity=Decimal(
                    "10200"
                ),
                benchmark_value=Decimal(
                    "10150"
                ),
                model_return_pct=Decimal(
                    "2"
                ),
                benchmark_return_pct=Decimal(
                    "1.5"
                ),
                excess_return_pct=Decimal(
                    "0.5"
                ),
            ),
        ),
    )


def history():

    return [
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
            "10200",
        ),
    ]


def test_empty_equity_curve_rejected(
    tmp_path,
):

    service = (
        ReportChartService(
            tmp_path
        )
    )

    with pytest.raises(
        ReportChartError
    ):

        service.create_equity_curve(
            []
        )


def test_equity_curve_created(
    tmp_path,
):

    service = (
        ReportChartService(
            tmp_path
        )
    )

    path = (
        service.create_equity_curve(
            history()
        )
    )

    assert path.exists()

    assert (
        path.name
        == "equity_curve.png"
    )


def test_spy_chart_created(
    tmp_path,
):

    service = (
        ReportChartService(
            tmp_path
        )
    )

    path = (
        service.create_model_vs_spy(
            spy_comparison()
        )
    )

    assert path.exists()

    assert (
        path.name
        == "model_vs_spy.png"
    )


def test_equal_weight_chart_created(
    tmp_path,
):

    service = (
        ReportChartService(
            tmp_path
        )
    )

    path = (
        service
        .create_model_vs_equal_weight(
            equal_weight_comparison()
        )
    )

    assert path.exists()

    assert (
        path.name
        == "model_vs_equal_weight.png"
    )


def test_drawdown_chart_created(
    tmp_path,
):

    service = (
        ReportChartService(
            tmp_path
        )
    )

    path = (
        service.create_drawdown_chart(
            history()
        )
    )

    assert path.exists()

    assert (
        path.name
        == "drawdown.png"
    )


def test_empty_spy_points_rejected(
    tmp_path,
):

    comparison = (
        spy_comparison()
    )

    bad = (
        BenchmarkComparison(
            symbol=(
                comparison.symbol
            ),
            starting_model_equity=(
                comparison
                .starting_model_equity
            ),
            starting_benchmark_price=(
                comparison
                .starting_benchmark_price
            ),
            ending_model_equity=(
                comparison
                .ending_model_equity
            ),
            ending_benchmark_price=(
                comparison
                .ending_benchmark_price
            ),
            model_total_return_pct=(
                comparison
                .model_total_return_pct
            ),
            benchmark_total_return_pct=(
                comparison
                .benchmark_total_return_pct
            ),
            excess_return_pct=(
                comparison
                .excess_return_pct
            ),
            points=(),
        )
    )

    with pytest.raises(
        ReportChartError
    ):

        ReportChartService(
            tmp_path
        ).create_model_vs_spy(
            bad
        )


def test_empty_equal_weight_points_rejected(
    tmp_path,
):

    comparison = (
        equal_weight_comparison()
    )

    bad = (
        EqualWeightBenchmarkComparison(
            symbols=(
                comparison.symbols
            ),
            starting_equity=(
                comparison
                .starting_equity
            ),
            ending_equity=(
                comparison
                .ending_equity
            ),
            starting_benchmark_value=(
                comparison
                .starting_benchmark_value
            ),
            ending_benchmark_value=(
                comparison
                .ending_benchmark_value
            ),
            model_total_return_pct=(
                comparison
                .model_total_return_pct
            ),
            benchmark_total_return_pct=(
                comparison
                .benchmark_total_return_pct
            ),
            excess_return_pct=(
                comparison
                .excess_return_pct
            ),
            points=(),
        )
    )

    with pytest.raises(
        ReportChartError
    ):

        ReportChartService(
            tmp_path
        ).create_model_vs_equal_weight(
            bad
        )


def test_nonpositive_equity_drawdown_rejected(
    tmp_path,
):

    with pytest.raises(
        ReportChartError
    ):

        ReportChartService(
            tmp_path
        ).create_drawdown_chart(
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
                    "0",
                ),
            ]
        )


def test_create_all_creates_four_files(
    tmp_path,
):

    result = (
        ReportChartService(
            tmp_path
        ).create_all(
            equity_history=(
                history()
            ),
            benchmark_comparison=(
                spy_comparison()
            ),
            equal_weight_comparison=(
                equal_weight_comparison()
            ),
        )
    )

    assert (
        result
        .equity_curve_path
        .exists()
    )

    assert (
        result
        .model_vs_spy_path
        .exists()
    )

    assert (
        result
        .model_vs_equal_weight_path
        .exists()
    )

    assert (
        result
        .drawdown_path
        .exists()
    )