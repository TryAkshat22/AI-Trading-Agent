from __future__ import annotations

from datetime import (
    date,
    datetime,
    timezone,
)
from types import SimpleNamespace

import pytest

import app


class FakeRuntime:

    def __init__(
        self,
    ) -> None:

        self.decision_calls = []
        self.execution_calls = []
        self.status_calls = 0

        self.decision_result = (
            SimpleNamespace(
                total_tickers=10,
                successful_tickers=10,
                failed_tickers=0,
                orders_created=2,
            )
        )

        self.execution_result = (
            SimpleNamespace(
                discovered_order_count=3,
                filled_orders=2,
                rejected_orders=1,
                failed_orders=0,
                skipped_orders=0,
            )
        )

        self.status_result = (
            app.StatusSummary(
                account_id=(
                    "model1-paper"
                ),
                starting_cash=10_000,
                total_orders=5,
                pending_orders=2,
                filled_orders=2,
                rejected_orders=1,
                total_fills=2,
                portfolio_snapshots=2,
                execution_attempts=3,
            )
        )

    def run_decision(
        self,
        decision_timestamp,
    ):

        self.decision_calls.append(
            decision_timestamp
        )

        return (
            self.decision_result
        )

    def run_execution(
        self,
        execution_session,
    ):

        self.execution_calls.append(
            execution_session
        )

        return (
            self.execution_result
        )

    def get_status(
        self,
    ):

        self.status_calls += 1

        return (
            self.status_result
        )


def make_factory(
    runtime,
):

    return lambda: runtime


def test_parse_z_timestamp():

    result = app.parse_utc_datetime(
        "2026-09-11T21:00:00Z"
    )

    assert (
        result
        == datetime(
            2026,
            9,
            11,
            21,
            0,
            tzinfo=timezone.utc,
        )
    )


def test_timestamp_is_normalized_to_utc():

    result = app.parse_utc_datetime(
        "2026-09-11T17:00:00-04:00"
    )

    assert (
        result
        == datetime(
            2026,
            9,
            11,
            21,
            0,
            tzinfo=timezone.utc,
        )
    )


def test_naive_timestamp_is_rejected():

    with pytest.raises(
        Exception
    ):

        app.parse_utc_datetime(
            "2026-09-11T21:00:00"
        )


def test_date_parser():

    result = app.parse_date(
        "2026-09-11"
    )

    assert (
        result
        == date(
            2026,
            9,
            11,
        )
    )


def test_decision_command_runs():

    runtime = FakeRuntime()

    exit_code = app.main(
        argv=[
            "decision",
            "--timestamp",
            "2026-09-11T21:00:00Z",
        ],
        runtime_factory=(
            make_factory(
                runtime
            )
        ),
    )

    assert exit_code == 0

    assert (
        runtime.decision_calls
        == [
            datetime(
                2026,
                9,
                11,
                21,
                0,
                tzinfo=timezone.utc,
            )
        ]
    )


def test_decision_failures_return_nonzero():

    runtime = FakeRuntime()

    runtime.decision_result = (
        SimpleNamespace(
            total_tickers=10,
            successful_tickers=9,
            failed_tickers=1,
            orders_created=2,
        )
    )

    exit_code = app.main(
        argv=[
            "decision",
            "--timestamp",
            "2026-09-11T21:00:00Z",
        ],
        runtime_factory=(
            make_factory(
                runtime
            )
        ),
    )

    assert (
        exit_code
        == 1
    )


def test_execution_command_runs():

    runtime = FakeRuntime()

    exit_code = app.main(
        argv=[
            "execution",
            "--session",
            "2026-09-08",
        ],
        runtime_factory=(
            make_factory(
                runtime
            )
        ),
    )

    assert exit_code == 0

    assert (
        runtime.execution_calls
        == [
            date(
                2026,
                9,
                8,
            )
        ]
    )


def test_execution_failure_returns_nonzero():

    runtime = FakeRuntime()

    runtime.execution_result = (
        SimpleNamespace(
            discovered_order_count=2,
            filled_orders=1,
            rejected_orders=0,
            failed_orders=1,
            skipped_orders=0,
        )
    )

    exit_code = app.main(
        argv=[
            "execution",
            "--session",
            "2026-09-08",
        ],
        runtime_factory=(
            make_factory(
                runtime
            )
        ),
    )

    assert (
        exit_code
        == 1
    )


def test_status_command_runs():

    runtime = FakeRuntime()

    exit_code = app.main(
        argv=[
            "status"
        ],
        runtime_factory=(
            make_factory(
                runtime
            )
        ),
    )

    assert exit_code == 0

    assert (
        runtime.status_calls
        == 1
    )


def test_status_output(
    capsys,
):

    runtime = FakeRuntime()

    app.main(
        argv=[
            "status"
        ],
        runtime_factory=(
            make_factory(
                runtime
            )
        ),
    )

    output = (
        capsys
        .readouterr()
        .out
    )

    assert (
        "model1-paper"
        in output
    )

    assert (
        "Pending: 2"
        in output
    )

    assert (
        "Filled: 2"
        in output
    )

    assert (
        "Rejected: 1"
        in output
    )

    assert (
        "Execution attempts: 3"
        in output
    )


def test_runtime_error_returns_two(
    capsys,
):

    def broken_factory():

        raise (
            app.ApplicationRuntimeError(
                "Not configured."
            )
        )

    exit_code = app.main(
        argv=[
            "status"
        ],
        runtime_factory=(
            broken_factory
        ),
    )

    assert (
        exit_code
        == 2
    )

    error = (
        capsys
        .readouterr()
        .err
    )

    assert (
        "Not configured."
        in error
    )


def test_unexpected_runtime_error_returns_one(
    capsys,
):

    def broken_factory():

        raise RuntimeError(
            "Database unavailable."
        )

    exit_code = app.main(
        argv=[
            "status"
        ],
        runtime_factory=(
            broken_factory
        ),
    )

    assert (
        exit_code
        == 1
    )

    error = (
        capsys
        .readouterr()
        .err
    )

    assert (
        "RuntimeError"
        in error
    )


def test_decision_output(
    capsys,
):

    runtime = FakeRuntime()

    app.main(
        argv=[
            "decision",
            "--timestamp",
            "2026-09-11T21:00:00Z",
        ],
        runtime_factory=(
            make_factory(
                runtime
            )
        ),
    )

    output = (
        capsys
        .readouterr()
        .out
    )

    assert (
        "Decision run complete"
        in output
    )

    assert (
        "Tickers: 10"
        in output
    )

    assert (
        "Orders created: 2"
        in output
    )


def test_execution_output(
    capsys,
):

    runtime = FakeRuntime()

    app.main(
        argv=[
            "execution",
            "--session",
            "2026-09-08",
        ],
        runtime_factory=(
            make_factory(
                runtime
            )
        ),
    )

    output = (
        capsys
        .readouterr()
        .out
    )

    assert (
        "Execution run complete"
        in output
    )

    assert (
        "Orders discovered: 3"
        in output
    )

    assert (
        "Filled: 2"
        in output
    )

    assert (
        "Rejected: 1"
        in output
    )

def test_execution_check_parser():

    parser = app.create_parser()

    args = parser.parse_args(
        [
            "execution-check",
            "--session",
            "2026-09-14",
        ]
    )

    assert (
        args.command
        == "execution-check"
    )

    assert (
        args.session
        == date(
            2026,
            9,
            14,
        )
    )


def test_execution_check_does_not_build_runtime(
    monkeypatch,
):

    called = False

    def runtime_factory():

        nonlocal called

        called = True

        raise AssertionError(
            "Runtime should not be built."
        )

    monkeypatch.setattr(
        app,
        "run_execution_check_command",
        lambda execution_session: 1,
    )

    result = app.main(
        [
            "execution-check",
            "--session",
            "2026-09-14",
        ],
        runtime_factory=runtime_factory,
    )

    assert result == 1
    assert called is False

def test_portfolio_parser():

    parser = app.create_parser()

    args = parser.parse_args(
        [
            "portfolio",
        ]
    )

    assert (
        args.command
        == "portfolio"
    )


def test_portfolio_command_uses_runtime(
    monkeypatch,
):

    class FakeRuntime:

        def get_portfolio_report(
            self,
        ):

            return object()

    called = False

    def fake_print(
        report,
    ):

        nonlocal called

        called = True

    import evaluation.portfolio_report

    monkeypatch.setattr(
        evaluation.portfolio_report,
        "print_portfolio_report",
        fake_print,
    )

    result = (
        app.main(
            [
                "portfolio",
            ],
            runtime_factory=(
                lambda:
                FakeRuntime()
            ),
        )
    )

    assert result == 0
    assert called is True

def test_equity_snapshot_parser():

    parser = app.create_parser()

    args = parser.parse_args(
        [
            "equity-snapshot",
            "--session",
            "2026-09-14",
        ]
    )

    assert (
        args.command
        == "equity-snapshot"
    )

    assert (
        args.session
        == date(
            2026,
            9,
            14,
        )
    )


def test_equity_history_parser():

    parser = app.create_parser()

    args = parser.parse_args(
        [
            "equity-history",
        ]
    )

    assert (
        args.command
        == "equity-history"
    )


def test_equity_snapshot_command_uses_runtime():

    class Snapshot:

        valuation_session = date(
            2026,
            9,
            14,
        )

        total_equity = 10000
        cash = 9000
        market_value = 1000
        total_return_pct = 0
        exposure_pct = 10
        open_positions = 1

    class Result:

        snapshot = Snapshot()

    class FakeRuntime:

        def record_equity_snapshot(
            self,
            valuation_session,
        ):

            return Result()

    result = app.main(
        [
            "equity-snapshot",
            "--session",
            "2026-09-14",
        ],
        runtime_factory=lambda: FakeRuntime(),
    )

    assert result == 0


def test_equity_history_command_uses_runtime():

    class FakeRuntime:

        def get_equity_history(
            self,
        ):

            return ()

    result = app.main(
        [
            "equity-history",
        ],
        runtime_factory=lambda: FakeRuntime(),
    )

    assert result == 0


def test_benchmark_parser():

    parser = app.create_parser()

    args = parser.parse_args(
        [
            "benchmark",
        ]
    )

    assert (
        args.command
        == "benchmark"
    )


def test_benchmark_command_uses_runtime(
    monkeypatch,
):

    class FakeRuntime:

        def get_benchmark_comparison(
            self,
        ):

            return object()

    called = False

    def fake_print(
        comparison,
    ):

        nonlocal called

        called = True

    import evaluation.benchmark

    monkeypatch.setattr(
        evaluation.benchmark,
        "print_benchmark_comparison",
        fake_print,
    )

    result = app.main(
        [
            "benchmark",
        ],
        runtime_factory=(
            lambda:
            FakeRuntime()
        ),
    )

    assert result == 0
    assert called is True


def test_metrics_parser():

    parser = (
        app.create_parser()
    )

    args = (
        parser.parse_args(
            [
                "metrics",
            ]
        )
    )

    assert (
        args.command
        == "metrics"
    )


def test_metrics_command_uses_runtime(
    monkeypatch,
):

    class FakeRuntime:

        def get_performance_metrics(
            self,
        ):

            return object()

    called = False

    def fake_print(
        metrics,
    ):

        nonlocal called

        called = True

    import evaluation.performance_metrics

    monkeypatch.setattr(
        evaluation.performance_metrics,
        "print_performance_metrics",
        fake_print,
    )

    result = (
        app.main(
            [
                "metrics",
            ],
            runtime_factory=(
                lambda:
                FakeRuntime()
            ),
        )
    )

    assert result == 0
    assert called is True

def test_equal_weight_benchmark_parser():

    parser = (
        app.create_parser()
    )

    args = (
        parser.parse_args(
            [
                "equal-weight-benchmark",
            ]
        )
    )

    assert (
        args.command
        == "equal-weight-benchmark"
    )


def test_equal_weight_benchmark_command_uses_runtime(
    monkeypatch,
):

    class FakeRuntime:

        def get_equal_weight_benchmark_comparison(
            self,
        ):

            return object()

    called = False

    def fake_print(
        comparison,
    ):

        nonlocal called

        called = True

    import evaluation.equal_weight_benchmark

    monkeypatch.setattr(
        evaluation.equal_weight_benchmark,
        "print_equal_weight_benchmark",
        fake_print,
    )

    result = (
        app.main(
            [
                "equal-weight-benchmark",
            ],
            runtime_factory=(
                lambda:
                FakeRuntime()
            ),
        )
    )

    assert result == 0
    assert called is True

def test_evaluation_parser():

    parser = (
        app.create_parser()
    )

    args = (
        parser.parse_args(
            [
                "evaluation",
            ]
        )
    )

    assert (
        args.command
        == "evaluation"
    )


def test_evaluation_command_uses_runtime(
    monkeypatch,
):

    class FakeRuntime:

        def get_evaluation_report(
            self,
        ):

            return object()

    called = False

    def fake_print(
        report,
    ):

        nonlocal called

        called = True

    import evaluation.evaluation_report

    monkeypatch.setattr(
        evaluation.evaluation_report,
        "print_evaluation_report",
        fake_print,
    )

    result = (
        app.main(
            [
                "evaluation",
            ],
            runtime_factory=(
                lambda:
                FakeRuntime()
            ),
        )
    )

    assert result == 0
    assert called is True

def test_export_report_parser():

    parser = (
        app.create_parser()
    )

    args = (
        parser.parse_args(
            [
                "export-report",
            ]
        )
    )

    assert (
        args.command
        == "export-report"
    )


def test_export_report_command_uses_runtime(
    monkeypatch,
):

    class FakeRuntime:

        def export_report(
            self,
        ):

            return object()

    called = False

    def fake_print(
        result,
    ):

        nonlocal called

        called = True

    import evaluation.report_bundle

    monkeypatch.setattr(
        evaluation.report_bundle,
        "print_report_bundle_result",
        fake_print,
    )

    result = (
        app.main(
            [
                "export-report",
            ],
            runtime_factory=(
                lambda:
                FakeRuntime()
            ),
        )
    )

    assert result == 0
    assert called is True