import csv
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
from evaluation.evaluation_report import (
    EvaluationReport,
)
from evaluation.report_export import (
    ReportExportError,
    ReportExportService,
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


def evaluation_report():

    return EvaluationReport(
        account_id="model1-paper",
        model_version="model-1",
        start_session=date(
            2026,
            9,
            14,
        ),
        end_session=date(
            2026,
            9,
            15,
        ),
        observations=2,
        model_total_return_pct=Decimal(
            "2"
        ),
        benchmark_symbol="SPY",
        benchmark_total_return_pct=Decimal(
            "1"
        ),
        excess_vs_benchmark_pct=Decimal(
            "1"
        ),
        cash_total_return_pct=Decimal(
            "0"
        ),
        excess_vs_cash_pct=Decimal(
            "2"
        ),
        equal_weight_total_return_pct=Decimal(
            "1.5"
        ),
        excess_vs_equal_weight_pct=Decimal(
            "0.5"
        ),
        annualized_volatility_pct=Decimal(
            "12"
        ),
        sharpe_ratio=Decimal(
            "1.2"
        ),
        sortino_ratio=Decimal(
            "1.6"
        ),
        max_drawdown_pct=Decimal(
            "3"
        ),
        positive_day_rate_pct=Decimal(
            "60"
        ),
        negative_day_rate_pct=Decimal(
            "40"
        ),
        best_day_pct=Decimal(
            "2"
        ),
        worst_day_pct=Decimal(
            "-1"
        ),
        average_daily_return_pct=Decimal(
            "0.1"
        ),
    )


def test_empty_equity_history_rejected(
    tmp_path,
):

    service = (
        ReportExportService(
            tmp_path
        )
    )

    with pytest.raises(
        ReportExportError
    ):

        service.export_equity_history(
            []
        )


def test_export_creates_directory(
    tmp_path,
):

    output = (
        tmp_path
        / "reports"
    )

    service = (
        ReportExportService(
            output
        )
    )

    service.export_equity_history(
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

    assert (
        output.is_dir()
    )


def test_equity_csv_created(
    tmp_path,
):

    service = (
        ReportExportService(
            tmp_path
        )
    )

    path = (
        service.export_equity_history(
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

    assert path.exists()

    assert (
        path.name
        == "equity_history.csv"
    )


def test_equity_history_sorted(
    tmp_path,
):

    service = (
        ReportExportService(
            tmp_path
        )
    )

    path = (
        service.export_equity_history(
            [
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
                        14,
                    ),
                    "10000",
                ),
            ]
        )
    )

    with path.open(
        newline="",
        encoding="utf-8",
    ) as file:

        rows = list(
            csv.DictReader(
                file
            )
        )

    assert (
        rows[
            0
        ][
            "valuation_session"
        ]
        == "2026-09-14"
    )

    assert (
        rows[
            1
        ][
            "valuation_session"
        ]
        == "2026-09-15"
    )


def test_equity_values_preserved(
    tmp_path,
):

    service = (
        ReportExportService(
            tmp_path
        )
    )

    path = (
        service.export_equity_history(
            [
                snapshot(
                    date(
                        2026,
                        9,
                        14,
                    ),
                    "10123.45",
                )
            ]
        )
    )

    with path.open(
        newline="",
        encoding="utf-8",
    ) as file:

        row = next(
            csv.DictReader(
                file
            )
        )

    assert (
        row[
            "total_equity"
        ]
        == "10123.45"
    )


def test_evaluation_csv_created(
    tmp_path,
):

    service = (
        ReportExportService(
            tmp_path
        )
    )

    path = (
        service
        .export_evaluation_summary(
            evaluation_report()
        )
    )

    assert path.exists()

    assert (
        path.name
        == "evaluation_summary.csv"
    )


def test_evaluation_metrics_preserved(
    tmp_path,
):

    service = (
        ReportExportService(
            tmp_path
        )
    )

    path = (
        service
        .export_evaluation_summary(
            evaluation_report()
        )
    )

    with path.open(
        newline="",
        encoding="utf-8",
    ) as file:

        rows = {
            row[
                "metric"
            ]: row[
                "value"
            ]
            for row
            in csv.DictReader(
                file
            )
        }

    assert (
        rows[
            "model_total_return_pct"
        ]
        == "2"
    )

    assert (
        rows[
            "benchmark_symbol"
        ]
        == "SPY"
    )

    assert (
        rows[
            "sharpe_ratio"
        ]
        == "1.2"
    )


def test_export_all_creates_both_files(
    tmp_path,
):

    service = (
        ReportExportService(
            tmp_path
        )
    )

    result = (
        service.export_all(
            equity_history=[
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
            ],
            report=(
                evaluation_report()
            ),
        )
    )

    assert (
        result
        .equity_history_path
        .exists()
    )

    assert (
        result
        .evaluation_summary_path
        .exists()
    )