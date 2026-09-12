from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Sequence

from database.equity_storage import (
    EquitySnapshot,
)
from evaluation.benchmark import (
    BenchmarkService,
)
from evaluation.cash_benchmark import (
    CashBenchmarkService,
)
from evaluation.equal_weight_benchmark import (
    EqualWeightBenchmarkService,
)
from evaluation.performance_metrics import (
    PerformanceMetricService,
)


class EvaluationReportError(
    Exception
):
    pass


@dataclass(frozen=True)
class EvaluationReport:

    account_id: str
    model_version: str

    start_session: date
    end_session: date
    observations: int

    model_total_return_pct: Decimal

    benchmark_symbol: str
    benchmark_total_return_pct: Decimal
    excess_vs_benchmark_pct: Decimal

    cash_total_return_pct: Decimal
    excess_vs_cash_pct: Decimal

    equal_weight_total_return_pct: Decimal
    excess_vs_equal_weight_pct: Decimal

    annualized_volatility_pct: Decimal
    sharpe_ratio: Decimal | None
    sortino_ratio: Decimal | None
    max_drawdown_pct: Decimal

    positive_day_rate_pct: Decimal
    negative_day_rate_pct: Decimal

    best_day_pct: Decimal
    worst_day_pct: Decimal
    average_daily_return_pct: Decimal


class EvaluationReportService:
    """
    Combines all read-only model evaluation layers
    into a single research report.
    """

    def __init__(
        self,
        benchmark_service: BenchmarkService,
        cash_benchmark_service: CashBenchmarkService,
        equal_weight_benchmark_service:
        EqualWeightBenchmarkService,
        performance_metric_service:
        PerformanceMetricService,
    ) -> None:

        self.benchmark_service = (
            benchmark_service
        )

        self.cash_benchmark_service = (
            cash_benchmark_service
        )

        self.equal_weight_benchmark_service = (
            equal_weight_benchmark_service
        )

        self.performance_metric_service = (
            performance_metric_service
        )

    def build(
        self,
        equity_history: Sequence[
            EquitySnapshot
        ],
    ) -> EvaluationReport:

        snapshots = tuple(
            sorted(
                equity_history,
                key=lambda snapshot:
                snapshot.valuation_session,
            )
        )

        if not snapshots:

            raise EvaluationReportError(
                "Equity history is empty."
            )

        account_ids = {
            snapshot.account_id
            for snapshot in snapshots
        }

        if len(
            account_ids
        ) != 1:

            raise EvaluationReportError(
                "Equity history contains "
                "multiple accounts."
            )

        model_versions = {
            snapshot.model_version
            for snapshot in snapshots
        }

        if len(
            model_versions
        ) != 1:

            raise EvaluationReportError(
                "Equity history contains "
                "multiple model versions."
            )

        benchmark = (
            self.benchmark_service
            .compare(
                snapshots
            )
        )

        cash = (
            self.cash_benchmark_service
            .compare(
                snapshots
            )
        )

        equal_weight = (
            self.equal_weight_benchmark_service
            .compare(
                snapshots
            )
        )

        metrics = (
            self.performance_metric_service
            .calculate(
                snapshots
            )
        )

        model_returns = (
            benchmark.model_total_return_pct,
            cash.model_total_return_pct,
            equal_weight.model_total_return_pct,
            metrics.total_return_pct,
        )

        if any(
            value
            != model_returns[0]
            for value
            in model_returns[1:]
        ):

            raise EvaluationReportError(
                "Model return is inconsistent "
                "across evaluation services."
            )

        return EvaluationReport(
            account_id=(
                snapshots[
                    0
                ].account_id
            ),
            model_version=(
                snapshots[
                    0
                ].model_version
            ),
            start_session=(
                snapshots[
                    0
                ].valuation_session
            ),
            end_session=(
                snapshots[
                    -1
                ].valuation_session
            ),
            observations=(
                len(
                    snapshots
                )
            ),
            model_total_return_pct=(
                metrics.total_return_pct
            ),
            benchmark_symbol=(
                benchmark.symbol
            ),
            benchmark_total_return_pct=(
                benchmark
                .benchmark_total_return_pct
            ),
            excess_vs_benchmark_pct=(
                benchmark
                .excess_return_pct
            ),
            cash_total_return_pct=(
                cash
                .cash_total_return_pct
            ),
            excess_vs_cash_pct=(
                cash
                .excess_return_pct
            ),
            equal_weight_total_return_pct=(
                equal_weight
                .benchmark_total_return_pct
            ),
            excess_vs_equal_weight_pct=(
                equal_weight
                .excess_return_pct
            ),
            annualized_volatility_pct=(
                metrics
                .annualized_volatility_pct
            ),
            sharpe_ratio=(
                metrics.sharpe_ratio
            ),
            sortino_ratio=(
                metrics.sortino_ratio
            ),
            max_drawdown_pct=(
                metrics.max_drawdown_pct
            ),
            positive_day_rate_pct=(
                metrics
                .positive_day_rate_pct
            ),
            negative_day_rate_pct=(
                metrics
                .negative_day_rate_pct
            ),
            best_day_pct=(
                metrics.best_day_pct
            ),
            worst_day_pct=(
                metrics.worst_day_pct
            ),
            average_daily_return_pct=(
                metrics
                .average_daily_return_pct
            ),
        )


def print_evaluation_report(
    report: EvaluationReport,
) -> None:

    print()
    print(
        "Model 1 Evaluation Report"
    )
    print(
        "========================="
    )

    print(
        f"Account:              "
        f"{report.account_id}"
    )

    print(
        f"Model:                "
        f"{report.model_version}"
    )

    print(
        f"Period:               "
        f"{report.start_session} "
        f"to {report.end_session}"
    )

    print(
        f"Observations:         "
        f"{report.observations}"
    )

    print()

    print(
        "Returns"
    )
    print(
        "-------"
    )

    print(
        f"Model:                "
        f"{report.model_total_return_pct:.2f}%"
    )

    print(
        f"{report.benchmark_symbol}:"
        f"{' ' * max(1, 19 - len(report.benchmark_symbol))}"
        f"{report.benchmark_total_return_pct:.2f}%"
    )

    print(
        f"Cash:                 "
        f"{report.cash_total_return_pct:.2f}%"
    )

    print(
        f"Equal-weight:         "
        f"{report.equal_weight_total_return_pct:.2f}%"
    )

    print()

    print(
        "Excess Return"
    )
    print(
        "-------------"
    )

    print(
        f"vs {report.benchmark_symbol}:"
        f"{' ' * max(1, 16 - len(report.benchmark_symbol))}"
        f"{report.excess_vs_benchmark_pct:.2f}%"
    )

    print(
        f"vs Cash:              "
        f"{report.excess_vs_cash_pct:.2f}%"
    )

    print(
        f"vs Equal-weight:      "
        f"{report.excess_vs_equal_weight_pct:.2f}%"
    )

    print()

    print(
        "Risk"
    )
    print(
        "----"
    )

    print(
        f"Annualized volatility:"
        f" {report.annualized_volatility_pct:.2f}%"
    )

    print(
        f"Maximum drawdown:     "
        f"{report.max_drawdown_pct:.2f}%"
    )

    if report.sharpe_ratio is None:

        print(
            "Sharpe ratio:         "
            "N/A"
        )

    else:

        print(
            f"Sharpe ratio:         "
            f"{report.sharpe_ratio:.3f}"
        )

    if report.sortino_ratio is None:

        print(
            "Sortino ratio:        "
            "N/A"
        )

    else:

        print(
            f"Sortino ratio:        "
            f"{report.sortino_ratio:.3f}"
        )

    print()

    print(
        "Daily Performance"
    )
    print(
        "-----------------"
    )

    print(
        f"Average daily return: "
        f"{report.average_daily_return_pct:.4f}%"
    )

    print(
        f"Positive-day rate:    "
        f"{report.positive_day_rate_pct:.2f}%"
    )

    print(
        f"Negative-day rate:    "
        f"{report.negative_day_rate_pct:.2f}%"
    )

    print(
        f"Best day:             "
        f"{report.best_day_pct:.2f}%"
    )

    print(
        f"Worst day:            "
        f"{report.worst_day_pct:.2f}%"
    )