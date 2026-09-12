from pathlib import Path
from types import SimpleNamespace

from evaluation.report_bundle import (
    ReportBundleService,
)


class FakeExportService:

    def __init__(
        self,
        output_directory,
    ):

        self.output_directory = Path(
            output_directory
        )

        self.calls = []

    def export_all(
        self,
        *,
        equity_history,
        report,
    ):

        self.calls.append(
            (
                equity_history,
                report,
            )
        )

        return SimpleNamespace(
            output_directory=(
                self.output_directory
            ),
            equity_history_path=(
                self.output_directory
                / "equity_history.csv"
            ),
            evaluation_summary_path=(
                self.output_directory
                / "evaluation_summary.csv"
            ),
        )


class FakeChartService:

    def __init__(
        self,
        output_directory,
    ):

        self.output_directory = Path(
            output_directory
        )

        self.calls = []

    def create_all(
        self,
        *,
        equity_history,
        benchmark_comparison,
        equal_weight_comparison,
    ):

        self.calls.append(
            (
                equity_history,
                benchmark_comparison,
                equal_weight_comparison,
            )
        )

        return SimpleNamespace(
            output_directory=(
                self.output_directory
            ),
            equity_curve_path=(
                self.output_directory
                / "equity_curve.png"
            ),
            model_vs_spy_path=(
                self.output_directory
                / "model_vs_spy.png"
            ),
            model_vs_equal_weight_path=(
                self.output_directory
                / "model_vs_equal_weight.png"
            ),
            drawdown_path=(
                self.output_directory
                / "drawdown.png"
            ),
        )


def test_bundle_calls_export_service(
    tmp_path,
):

    export_service = (
        FakeExportService(
            tmp_path
        )
    )

    chart_service = (
        FakeChartService(
            tmp_path
        )
    )

    service = (
        ReportBundleService(
            export_service=(
                export_service
            ),
            chart_service=(
                chart_service
            ),
        )
    )

    history = [
        object(),
    ]

    report = object()

    service.create(
        equity_history=history,
        evaluation_report=report,
        benchmark_comparison=object(),
        equal_weight_comparison=object(),
    )

    assert (
        export_service.calls
        == [
            (
                history,
                report,
            )
        ]
    )


def test_bundle_calls_chart_service(
    tmp_path,
):

    export_service = (
        FakeExportService(
            tmp_path
        )
    )

    chart_service = (
        FakeChartService(
            tmp_path
        )
    )

    service = (
        ReportBundleService(
            export_service=(
                export_service
            ),
            chart_service=(
                chart_service
            ),
        )
    )

    history = [
        object(),
    ]

    spy = object()
    equal_weight = object()

    service.create(
        equity_history=history,
        evaluation_report=object(),
        benchmark_comparison=spy,
        equal_weight_comparison=(
            equal_weight
        ),
    )

    assert (
        chart_service.calls
        == [
            (
                history,
                spy,
                equal_weight,
            )
        ]
    )


def test_bundle_preserves_output_directory(
    tmp_path,
):

    service = (
        ReportBundleService(
            export_service=(
                FakeExportService(
                    tmp_path
                )
            ),
            chart_service=(
                FakeChartService(
                    tmp_path
                )
            ),
        )
    )

    result = service.create(
        equity_history=[
            object(),
        ],
        evaluation_report=object(),
        benchmark_comparison=object(),
        equal_weight_comparison=object(),
    )

    assert (
        result.output_directory
        == tmp_path
    )


def test_bundle_contains_export_result(
    tmp_path,
):

    result = (
        ReportBundleService(
            export_service=(
                FakeExportService(
                    tmp_path
                )
            ),
            chart_service=(
                FakeChartService(
                    tmp_path
                )
            ),
        )
        .create(
            equity_history=[
                object(),
            ],
            evaluation_report=object(),
            benchmark_comparison=object(),
            equal_weight_comparison=object(),
        )
    )

    assert (
        result
        .export_result
        .equity_history_path
        .name
        == "equity_history.csv"
    )


def test_bundle_contains_chart_result(
    tmp_path,
):

    result = (
        ReportBundleService(
            export_service=(
                FakeExportService(
                    tmp_path
                )
            ),
            chart_service=(
                FakeChartService(
                    tmp_path
                )
            ),
        )
        .create(
            equity_history=[
                object(),
            ],
            evaluation_report=object(),
            benchmark_comparison=object(),
            equal_weight_comparison=object(),
        )
    )

    assert (
        result
        .chart_result
        .drawdown_path
        .name
        == "drawdown.png"
    )