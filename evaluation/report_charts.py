from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import matplotlib.pyplot as plt

from database.equity_storage import (
    EquitySnapshot,
)
from evaluation.benchmark import (
    BenchmarkComparison,
)
from evaluation.equal_weight_benchmark import (
    EqualWeightBenchmarkComparison,
)


class ReportChartError(Exception):
    pass


@dataclass(frozen=True)
class ReportChartResult:
    output_directory: Path
    equity_curve_path: Path
    model_vs_spy_path: Path
    model_vs_equal_weight_path: Path
    drawdown_path: Path


class ReportChartService:
    """
    Presentation-only chart generation.

    This service reads evaluation data and writes PNG files.
    It never modifies trading or portfolio state.
    """

    def __init__(
        self,
        output_directory: str | Path,
    ) -> None:

        self.output_directory = Path(
            output_directory
        )

    def _prepare_directory(
        self,
    ) -> None:

        self.output_directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        if not self.output_directory.is_dir():

            raise ReportChartError(
                "Chart output path is not a directory."
            )

    @staticmethod
    def _sorted_history(
        equity_history: Sequence[
            EquitySnapshot
        ],
    ) -> tuple[
        EquitySnapshot,
        ...,
    ]:

        snapshots = tuple(
            sorted(
                equity_history,
                key=lambda snapshot:
                snapshot.valuation_session,
            )
        )

        if not snapshots:

            raise ReportChartError(
                "Equity history is empty."
            )

        return snapshots

    def create_equity_curve(
        self,
        equity_history: Sequence[
            EquitySnapshot
        ],
    ) -> Path:

        snapshots = (
            self._sorted_history(
                equity_history
            )
        )

        self._prepare_directory()

        sessions = [
            snapshot.valuation_session
            for snapshot in snapshots
        ]

        equities = [
            float(
                snapshot.total_equity
            )
            for snapshot in snapshots
        ]

        output_path = (
            self.output_directory
            / "equity_curve.png"
        )

        figure, axis = plt.subplots()

        axis.plot(
            sessions,
            equities,
            marker="o",
        )

        axis.set_title(
            "Model 1 Equity Curve"
        )

        axis.set_xlabel(
            "Session"
        )

        axis.set_ylabel(
            "Portfolio Equity ($)"
        )

        axis.grid(
            True,
            alpha=0.3,
        )

        figure.autofmt_xdate()

        figure.tight_layout()

        figure.savefig(
            output_path,
            dpi=150,
            bbox_inches="tight",
        )

        plt.close(
            figure
        )

        return output_path

    def create_model_vs_spy(
        self,
        comparison: BenchmarkComparison,
    ) -> Path:

        if not comparison.points:

            raise ReportChartError(
                "Benchmark comparison has no points."
            )

        self._prepare_directory()

        sessions = [
            point.session
            for point in comparison.points
        ]

        model_returns = [
            float(
                point.model_return_pct
            )
            for point in comparison.points
        ]

        benchmark_returns = [
            float(
                point.benchmark_return_pct
            )
            for point in comparison.points
        ]

        output_path = (
            self.output_directory
            / "model_vs_spy.png"
        )

        figure, axis = plt.subplots()

        axis.plot(
            sessions,
            model_returns,
            marker="o",
            label="Model 1",
        )

        axis.plot(
            sessions,
            benchmark_returns,
            marker="o",
            label=comparison.symbol,
        )

        axis.set_title(
            f"Model 1 vs {comparison.symbol}"
        )

        axis.set_xlabel(
            "Session"
        )

        axis.set_ylabel(
            "Cumulative Return (%)"
        )

        axis.legend()

        axis.grid(
            True,
            alpha=0.3,
        )

        figure.autofmt_xdate()

        figure.tight_layout()

        figure.savefig(
            output_path,
            dpi=150,
            bbox_inches="tight",
        )

        plt.close(
            figure
        )

        return output_path

    def create_model_vs_equal_weight(
        self,
        comparison:
        EqualWeightBenchmarkComparison,
    ) -> Path:

        if not comparison.points:

            raise ReportChartError(
                "Equal-weight comparison "
                "has no points."
            )

        self._prepare_directory()

        sessions = [
            point.session
            for point in comparison.points
        ]

        model_returns = [
            float(
                point.model_return_pct
            )
            for point in comparison.points
        ]

        benchmark_returns = [
            float(
                point.benchmark_return_pct
            )
            for point in comparison.points
        ]

        output_path = (
            self.output_directory
            / "model_vs_equal_weight.png"
        )

        figure, axis = plt.subplots()

        axis.plot(
            sessions,
            model_returns,
            marker="o",
            label="Model 1",
        )

        axis.plot(
            sessions,
            benchmark_returns,
            marker="o",
            label=(
                "Equal-Weight "
                "Buy-and-Hold"
            ),
        )

        axis.set_title(
            "Model 1 vs Equal-Weight Buy-and-Hold"
        )

        axis.set_xlabel(
            "Session"
        )

        axis.set_ylabel(
            "Cumulative Return (%)"
        )

        axis.legend()

        axis.grid(
            True,
            alpha=0.3,
        )

        figure.autofmt_xdate()

        figure.tight_layout()

        figure.savefig(
            output_path,
            dpi=150,
            bbox_inches="tight",
        )

        plt.close(
            figure
        )

        return output_path

    def create_drawdown_chart(
        self,
        equity_history: Sequence[
            EquitySnapshot
        ],
    ) -> Path:

        snapshots = (
            self._sorted_history(
                equity_history
            )
        )

        self._prepare_directory()

        sessions = []

        drawdowns = []

        peak = float(
            snapshots[
                0
            ].total_equity
        )

        if peak <= 0:

            raise ReportChartError(
                "Equity must be positive."
            )

        for snapshot in snapshots:

            equity = float(
                snapshot.total_equity
            )

            if equity <= 0:

                raise ReportChartError(
                    "Equity must be positive."
                )

            if equity > peak:

                peak = equity

            drawdown_pct = (
                (
                    equity
                    / peak
                )
                - 1
            ) * 100

            sessions.append(
                snapshot.valuation_session
            )

            drawdowns.append(
                drawdown_pct
            )

        output_path = (
            self.output_directory
            / "drawdown.png"
        )

        figure, axis = plt.subplots()

        axis.plot(
            sessions,
            drawdowns,
            marker="o",
        )

        axis.axhline(
            0,
            linewidth=1,
        )

        axis.set_title(
            "Model 1 Drawdown"
        )

        axis.set_xlabel(
            "Session"
        )

        axis.set_ylabel(
            "Drawdown (%)"
        )

        axis.grid(
            True,
            alpha=0.3,
        )

        figure.autofmt_xdate()

        figure.tight_layout()

        figure.savefig(
            output_path,
            dpi=150,
            bbox_inches="tight",
        )

        plt.close(
            figure
        )

        return output_path

    def create_all(
        self,
        equity_history: Sequence[
            EquitySnapshot
        ],
        benchmark_comparison:
        BenchmarkComparison,
        equal_weight_comparison:
        EqualWeightBenchmarkComparison,
    ) -> ReportChartResult:

        equity_curve_path = (
            self.create_equity_curve(
                equity_history
            )
        )

        model_vs_spy_path = (
            self.create_model_vs_spy(
                benchmark_comparison
            )
        )

        model_vs_equal_weight_path = (
            self.create_model_vs_equal_weight(
                equal_weight_comparison
            )
        )

        drawdown_path = (
            self.create_drawdown_chart(
                equity_history
            )
        )

        return ReportChartResult(
            output_directory=(
                self.output_directory
            ),
            equity_curve_path=(
                equity_curve_path
            ),
            model_vs_spy_path=(
                model_vs_spy_path
            ),
            model_vs_equal_weight_path=(
                model_vs_equal_weight_path
            ),
            drawdown_path=(
                drawdown_path
            ),
        )