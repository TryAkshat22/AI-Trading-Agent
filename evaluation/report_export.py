from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from database.equity_storage import (
    EquitySnapshot,
)
from evaluation.evaluation_report import (
    EvaluationReport,
)


class ReportExportError(Exception):
    pass


@dataclass(frozen=True)
class ReportExportResult:
    output_directory: Path
    equity_history_path: Path
    evaluation_summary_path: Path


class ReportExportService:
    """
    Writes read-only evaluation outputs to CSV.

    This service never modifies:
    - orders
    - fills
    - portfolio state
    - equity snapshots
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

            raise ReportExportError(
                "Report output path is not "
                "a directory."
            )

    def export_equity_history(
        self,
        equity_history: Sequence[
            EquitySnapshot
        ],
    ) -> Path:

        snapshots = tuple(
            sorted(
                equity_history,
                key=lambda snapshot:
                snapshot.valuation_session,
            )
        )

        if not snapshots:

            raise ReportExportError(
                "Equity history is empty."
            )

        self._prepare_directory()

        output_path = (
            self.output_directory
            / "equity_history.csv"
        )

        with output_path.open(
            "w",
            newline="",
            encoding="utf-8",
        ) as file:

            writer = csv.writer(
                file
            )

            writer.writerow(
                [
                    "valuation_session",
                    "account_id",
                    "model_version",
                    "starting_cash",
                    "cash",
                    "market_value",
                    "total_equity",
                    "realized_pnl",
                    "unrealized_pnl",
                    "total_pnl",
                    "total_return_pct",
                    "exposure_pct",
                    "open_positions",
                    "recorded_at_utc",
                ]
            )

            for snapshot in snapshots:

                writer.writerow(
                    [
                        snapshot
                        .valuation_session
                        .isoformat(),

                        snapshot.account_id,

                        snapshot.model_version,

                        str(
                            snapshot
                            .starting_cash
                        ),

                        str(
                            snapshot.cash
                        ),

                        str(
                            snapshot
                            .market_value
                        ),

                        str(
                            snapshot
                            .total_equity
                        ),

                        str(
                            snapshot
                            .realized_pnl
                        ),

                        str(
                            snapshot
                            .unrealized_pnl
                        ),

                        str(
                            snapshot
                            .total_pnl
                        ),

                        str(
                            snapshot
                            .total_return_pct
                        ),

                        str(
                            snapshot
                            .exposure_pct
                        ),

                        snapshot
                        .open_positions,

                        snapshot
                        .recorded_at_utc
                        .isoformat(),
                    ]
                )

        return output_path

    def export_evaluation_summary(
        self,
        report: EvaluationReport,
    ) -> Path:

        self._prepare_directory()

        output_path = (
            self.output_directory
            / "evaluation_summary.csv"
        )

        rows = [
            (
                "account_id",
                report.account_id,
            ),
            (
                "model_version",
                report.model_version,
            ),
            (
                "start_session",
                report.start_session.isoformat(),
            ),
            (
                "end_session",
                report.end_session.isoformat(),
            ),
            (
                "observations",
                str(
                    report.observations
                ),
            ),
            (
                "model_total_return_pct",
                str(
                    report
                    .model_total_return_pct
                ),
            ),
            (
                "benchmark_symbol",
                report.benchmark_symbol,
            ),
            (
                "benchmark_total_return_pct",
                str(
                    report
                    .benchmark_total_return_pct
                ),
            ),
            (
                "excess_vs_benchmark_pct",
                str(
                    report
                    .excess_vs_benchmark_pct
                ),
            ),
            (
                "cash_total_return_pct",
                str(
                    report
                    .cash_total_return_pct
                ),
            ),
            (
                "excess_vs_cash_pct",
                str(
                    report
                    .excess_vs_cash_pct
                ),
            ),
            (
                "equal_weight_total_return_pct",
                str(
                    report
                    .equal_weight_total_return_pct
                ),
            ),
            (
                "excess_vs_equal_weight_pct",
                str(
                    report
                    .excess_vs_equal_weight_pct
                ),
            ),
            (
                "annualized_volatility_pct",
                str(
                    report
                    .annualized_volatility_pct
                ),
            ),
            (
                "sharpe_ratio",
                (
                    ""
                    if report.sharpe_ratio
                    is None
                    else str(
                        report.sharpe_ratio
                    )
                ),
            ),
            (
                "sortino_ratio",
                (
                    ""
                    if report.sortino_ratio
                    is None
                    else str(
                        report.sortino_ratio
                    )
                ),
            ),
            (
                "max_drawdown_pct",
                str(
                    report
                    .max_drawdown_pct
                ),
            ),
            (
                "positive_day_rate_pct",
                str(
                    report
                    .positive_day_rate_pct
                ),
            ),
            (
                "negative_day_rate_pct",
                str(
                    report
                    .negative_day_rate_pct
                ),
            ),
            (
                "best_day_pct",
                str(
                    report.best_day_pct
                ),
            ),
            (
                "worst_day_pct",
                str(
                    report.worst_day_pct
                ),
            ),
            (
                "average_daily_return_pct",
                str(
                    report
                    .average_daily_return_pct
                ),
            ),
        ]

        with output_path.open(
            "w",
            newline="",
            encoding="utf-8",
        ) as file:

            writer = csv.writer(
                file
            )

            writer.writerow(
                [
                    "metric",
                    "value",
                ]
            )

            writer.writerows(
                rows
            )

        return output_path

    def export_all(
        self,
        equity_history: Sequence[
            EquitySnapshot
        ],
        report: EvaluationReport,
    ) -> ReportExportResult:

        equity_path = (
            self.export_equity_history(
                equity_history
            )
        )

        evaluation_path = (
            self.export_evaluation_summary(
                report
            )
        )

        return ReportExportResult(
            output_directory=(
                self.output_directory
            ),
            equity_history_path=(
                equity_path
            ),
            evaluation_summary_path=(
                evaluation_path
            ),
        )