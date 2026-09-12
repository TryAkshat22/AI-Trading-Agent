from datetime import (
    date,
    datetime,
    timezone,
)
from decimal import Decimal
from types import SimpleNamespace

import pytest

from database.equity_storage import (
    EquitySnapshot,
)
from evaluation.evaluation_report import (
    EvaluationReportError,
    EvaluationReportService,
)


def snapshot(
    session: date,
    equity: str = "10000",
    account_id: str = "model1-paper",
    model_version: str = "model-1",
):

    value = Decimal(
        equity
    )

    return EquitySnapshot(
        snapshot_id=(
            f"snapshot-{session}"
        ),
        account_id=account_id,
        model_version=model_version,
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


class FakeBenchmarkService:

    def __init__(
        self,
        model_return="5",
    ):

        self.model_return = Decimal(
            model_return
        )

    def compare(
        self,
        history,
    ):

        return SimpleNamespace(
            symbol="SPY",
            model_total_return_pct=(
                self.model_return
            ),
            benchmark_total_return_pct=Decimal(
                "3"
            ),
            excess_return_pct=Decimal(
                "2"
            ),
        )


class FakeCashService:

    def __init__(
        self,
        model_return="5",
    ):

        self.model_return = Decimal(
            model_return
        )

    def compare(
        self,
        history,
    ):

        return SimpleNamespace(
            model_total_return_pct=(
                self.model_return
            ),
            cash_total_return_pct=Decimal(
                "0"
            ),
            excess_return_pct=Decimal(
                "5"
            ),
        )


class FakeEqualWeightService:

    def __init__(
        self,
        model_return="5",
    ):

        self.model_return = Decimal(
            model_return
        )

    def compare(
        self,
        history,
    ):

        return SimpleNamespace(
            model_total_return_pct=(
                self.model_return
            ),
            benchmark_total_return_pct=Decimal(
                "4"
            ),
            excess_return_pct=Decimal(
                "1"
            ),
        )


class FakeMetricService:

    def __init__(
        self,
        model_return="5",
        sharpe=Decimal(
            "1.25"
        ),
    ):

        self.model_return = Decimal(
            model_return
        )

        self.sharpe = sharpe

    def calculate(
        self,
        history,
    ):

        return SimpleNamespace(
            total_return_pct=(
                self.model_return
            ),
            annualized_volatility_pct=Decimal(
                "12"
            ),
            sharpe_ratio=self.sharpe,
            sortino_ratio=Decimal(
                "1.75"
            ),
            max_drawdown_pct=Decimal(
                "4"
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
                "0.10"
            ),
        )


def build_service(
    benchmark_return="5",
    cash_return="5",
    equal_return="5",
    metric_return="5",
    sharpe=Decimal(
        "1.25"
    ),
):

    return EvaluationReportService(
        benchmark_service=(
            FakeBenchmarkService(
                benchmark_return
            )
        ),
        cash_benchmark_service=(
            FakeCashService(
                cash_return
            )
        ),
        equal_weight_benchmark_service=(
            FakeEqualWeightService(
                equal_return
            )
        ),
        performance_metric_service=(
            FakeMetricService(
                metric_return,
                sharpe=sharpe,
            )
        ),
    )


def test_empty_history_rejected():

    with pytest.raises(
        EvaluationReportError
    ):

        build_service().build(
            []
        )


def test_combines_evaluation_results():

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

    report = (
        build_service()
        .build(
            history
        )
    )

    assert (
        report.model_total_return_pct
        == Decimal(
            "5"
        )
    )

    assert (
        report.benchmark_total_return_pct
        == Decimal(
            "3"
        )
    )

    assert (
        report.cash_total_return_pct
        == Decimal(
            "0"
        )
    )

    assert (
        report.equal_weight_total_return_pct
        == Decimal(
            "4"
        )
    )


def test_excess_returns_preserved():

    report = (
        build_service()
        .build(
            [
                snapshot(
                    date(
                        2026,
                        9,
                        14,
                    )
                ),
            ]
        )
    )

    assert (
        report.excess_vs_benchmark_pct
        == Decimal(
            "2"
        )
    )

    assert (
        report.excess_vs_cash_pct
        == Decimal(
            "5"
        )
    )

    assert (
        report.excess_vs_equal_weight_pct
        == Decimal(
            "1"
        )
    )


def test_history_sorted_for_report_period():

    report = (
        build_service()
        .build(
            [
                snapshot(
                    date(
                        2026,
                        9,
                        16,
                    )
                ),
                snapshot(
                    date(
                        2026,
                        9,
                        14,
                    )
                ),
                snapshot(
                    date(
                        2026,
                        9,
                        15,
                    )
                ),
            ]
        )
    )

    assert (
        report.start_session
        == date(
            2026,
            9,
            14,
        )
    )

    assert (
        report.end_session
        == date(
            2026,
            9,
            16,
        )
    )

    assert (
        report.observations
        == 3
    )


def test_mixed_accounts_rejected():

    history = [
        snapshot(
            date(
                2026,
                9,
                14,
            ),
            account_id="account-1",
        ),
        snapshot(
            date(
                2026,
                9,
                15,
            ),
            account_id="account-2",
        ),
    ]

    with pytest.raises(
        EvaluationReportError
    ):

        build_service().build(
            history
        )


def test_mixed_models_rejected():

    history = [
        snapshot(
            date(
                2026,
                9,
                14,
            ),
            model_version="model-1",
        ),
        snapshot(
            date(
                2026,
                9,
                15,
            ),
            model_version="model-2",
        ),
    ]

    with pytest.raises(
        EvaluationReportError
    ):

        build_service().build(
            history
        )


def test_inconsistent_model_returns_rejected():

    service = build_service(
        benchmark_return="5",
        cash_return="5",
        equal_return="5",
        metric_return="6",
    )

    with pytest.raises(
        EvaluationReportError
    ):

        service.build(
            [
                snapshot(
                    date(
                        2026,
                        9,
                        14,
                    )
                ),
            ]
        )


def test_none_sharpe_preserved():

    report = (
        build_service(
            sharpe=None
        )
        .build(
            [
                snapshot(
                    date(
                        2026,
                        9,
                        14,
                    )
                )
            ]
        )
    )

    assert (
        report.sharpe_ratio
        is None
    )