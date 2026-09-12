from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from database.equity_storage import (
    EquitySnapshot,
)
from evaluation.benchmark import (
    BenchmarkComparison,
)
from evaluation.equal_weight_benchmark import (
    EqualWeightBenchmarkComparison,
)
from evaluation.evaluation_report import (
    EvaluationReport,
)
from evaluation.report_charts import (
    ReportChartResult,
    ReportChartService,
)
from evaluation.report_export import (
    ReportExportResult,
    ReportExportService,
)


@dataclass(frozen=True)
class ReportBundleResult:
    output_directory: Path
    export_result: ReportExportResult
    chart_result: ReportChartResult


class ReportBundleService:
    """
    Produces the complete presentation package.

    Outputs:
    - equity_history.csv
    - evaluation_summary.csv
    - equity_curve.png
    - model_vs_spy.png
    - model_vs_equal_weight.png
    - drawdown.png

    This layer never modifies trading state.
    """

    def __init__(
        self,
        export_service: ReportExportService,
        chart_service: ReportChartService,
    ) -> None:

        self.export_service = (
            export_service
        )

        self.chart_service = (
            chart_service
        )

    def create(
        self,
        *,
        equity_history: Sequence[
            EquitySnapshot
        ],
        evaluation_report: EvaluationReport,
        benchmark_comparison:
        BenchmarkComparison,
        equal_weight_comparison:
        EqualWeightBenchmarkComparison,
    ) -> ReportBundleResult:

        exports = (
            self.export_service.export_all(
                equity_history=(
                    equity_history
                ),
                report=(
                    evaluation_report
                ),
            )
        )

        charts = (
            self.chart_service.create_all(
                equity_history=(
                    equity_history
                ),
                benchmark_comparison=(
                    benchmark_comparison
                ),
                equal_weight_comparison=(
                    equal_weight_comparison
                ),
            )
        )

        return ReportBundleResult(
            output_directory=(
                exports.output_directory
            ),
            export_result=exports,
            chart_result=charts,
        )


def print_report_bundle_result(
    result: ReportBundleResult,
) -> None:

    print()
    print(
        "Research Report Export"
    )
    print(
        "======================"
    )

    print(
        f"Output directory: "
        f"{result.output_directory}"
    )

    print()
    print(
        "CSV Files"
    )
    print(
        "---------"
    )

    print(
        result
        .export_result
        .equity_history_path
    )

    print(
        result
        .export_result
        .evaluation_summary_path
    )

    print()
    print(
        "Charts"
    )
    print(
        "------"
    )

    print(
        result
        .chart_result
        .equity_curve_path
    )

    print(
        result
        .chart_result
        .model_vs_spy_path
    )

    print(
        result
        .chart_result
        .model_vs_equal_weight_path
    )

    print(
        result
        .chart_result
        .drawdown_path
    )