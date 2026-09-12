from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Callable, Protocol, Sequence


class ApplicationRuntimeError(Exception):
    pass


class TradingApplication(Protocol):

    def run_decision(
        self,
        decision_timestamp: datetime,
    ):
        ...

    def run_execution(
        self,
        execution_session: date,
    ):
        ...

    def get_status(
        self,
    ):
        ...

    def get_portfolio_report(
        self,
    ):
        ...

    def record_equity_snapshot(
        self,
        valuation_session: date,
    ):
        ...

    def get_equity_history(
        self,
    ):
        ...

    def get_benchmark_comparison(
        self,
    ):
        ...

    def get_equal_weight_benchmark_comparison(
        self,
    ):
        ...

    def get_performance_metrics(
        self,
    ):
        ...

    def get_evaluation_report(
        self,
    ):
        ...

    def export_report(
        self,
    ):
        ...


@dataclass(frozen=True)
class StatusSummary:

    account_id: str | None = None
    starting_cash: object | None = None

    total_orders: int = 0
    pending_orders: int = 0
    filled_orders: int = 0
    rejected_orders: int = 0

    total_fills: int = 0
    portfolio_snapshots: int = 0
    execution_attempts: int = 0


def build_runtime() -> TradingApplication:

    from runtime import (
        build_live_runtime,
    )

    return build_live_runtime()


def parse_utc_datetime(
    value: str,
) -> datetime:

    normalized = value.strip()

    if not normalized:

        raise argparse.ArgumentTypeError(
            "Timestamp cannot be empty."
        )

    if normalized.endswith(
        "Z"
    ):

        normalized = (
            normalized[:-1]
            + "+00:00"
        )

    try:

        parsed = datetime.fromisoformat(
            normalized
        )

    except ValueError as exc:

        raise argparse.ArgumentTypeError(
            "Invalid ISO-8601 timestamp."
        ) from exc

    if parsed.tzinfo is None:

        raise argparse.ArgumentTypeError(
            "Timestamp must include a timezone."
        )

    return parsed.astimezone(
        timezone.utc
    )


def parse_date(
    value: str,
) -> date:

    try:

        return date.fromisoformat(
            value.strip()
        )

    except ValueError as exc:

        raise argparse.ArgumentTypeError(
            "Date must use YYYY-MM-DD."
        ) from exc


def create_parser() -> argparse.ArgumentParser:

    parser = argparse.ArgumentParser(
        prog="PaperTradingAgent",
        description=(
            "Autonomous paper-trading "
            "research agent."
        ),
    )

    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
    )

    # =================================================
    # DECISION
    # =================================================

    decision_parser = (
        subparsers.add_parser(
            "decision",
            help=(
                "Run the after-close "
                "decision cycle."
            ),
        )
    )

    decision_parser.add_argument(
        "--timestamp",
        type=parse_utc_datetime,
        default=None,
    )

    # =================================================
    # EXECUTION
    # =================================================

    execution_parser = (
        subparsers.add_parser(
            "execution",
            help=(
                "Process pending orders "
                "for an execution session."
            ),
        )
    )

    execution_parser.add_argument(
        "--session",
        type=parse_date,
        default=None,
    )

    # =================================================
    # EXECUTION CHECK
    # =================================================

    execution_check_parser = (
        subparsers.add_parser(
            "execution-check",
            help=(
                "Read-only execution "
                "readiness check."
            ),
        )
    )

    execution_check_parser.add_argument(
        "--session",
        type=parse_date,
        required=True,
    )

    # =================================================
    # PORTFOLIO
    # =================================================

    subparsers.add_parser(
        "portfolio",
        help=(
            "Show current portfolio "
            "performance."
        ),
    )

    # =================================================
    # EQUITY SNAPSHOT
    # =================================================

    equity_snapshot_parser = (
        subparsers.add_parser(
            "equity-snapshot",
            help=(
                "Persist one immutable "
                "portfolio equity snapshot."
            ),
        )
    )

    equity_snapshot_parser.add_argument(
        "--session",
        type=parse_date,
        required=True,
    )

    # =================================================
    # EQUITY HISTORY
    # =================================================

    subparsers.add_parser(
        "equity-history",
        help=(
            "Show persisted portfolio "
            "equity history."
        ),
    )

    # =================================================
    # MARKET BENCHMARK
    # =================================================

    subparsers.add_parser(
        "benchmark",
        help=(
            "Compare Model 1 with "
            "the configured market benchmark."
        ),
    )

    # =================================================
    # EQUAL-WEIGHT BENCHMARK
    # =================================================

    subparsers.add_parser(
        "equal-weight-benchmark",
        help=(
            "Compare Model 1 with a passive "
            "equal-weight buy-and-hold portfolio."
        ),
    )

    # =================================================
    # PERFORMANCE METRICS
    # =================================================

    subparsers.add_parser(
        "metrics",
        help=(
            "Calculate risk-adjusted "
            "performance metrics."
        ),
    )

    # =================================================
    # COMBINED EVALUATION
    # =================================================

    subparsers.add_parser(
        "evaluation",
        help=(
            "Show the combined model "
            "evaluation report."
        ),
    )

    # =================================================
    # EXPORT REPORT
    # =================================================

    subparsers.add_parser(
        "export-report",
        help=(
            "Export the complete research "
            "report package."
        ),
    )

    # =================================================
    # STATUS
    # =================================================

    subparsers.add_parser(
        "status",
        help=(
            "Show paper account status."
        ),
    )

    return parser


def run_decision_command(
    runtime: TradingApplication,
    timestamp: datetime | None,
) -> int:

    if timestamp is None:

        timestamp = datetime.now(
            timezone.utc
        )

    result = runtime.run_decision(
        decision_timestamp=timestamp
    )

    print(
        "Decision run complete"
    )

    print(
        f"Timestamp: "
        f"{timestamp.isoformat()}"
    )

    print(
        f"Tickers: "
        f"{result.total_tickers}"
    )

    print(
        f"Successful: "
        f"{result.successful_tickers}"
    )

    print(
        f"Failed: "
        f"{result.failed_tickers}"
    )

    print(
        f"Orders created: "
        f"{result.orders_created}"
    )

    return (
        1
        if result.failed_tickers > 0
        else 0
    )


def run_execution_command(
    runtime: TradingApplication,
    execution_session: date | None,
) -> int:

    if execution_session is None:

        execution_session = (
            datetime.now(
                timezone.utc
            ).date()
        )

    result = runtime.run_execution(
        execution_session=(
            execution_session
        )
    )

    print(
        "Execution run complete"
    )

    print(
        f"Session: "
        f"{execution_session.isoformat()}"
    )

    print(
        f"Orders discovered: "
        f"{result.discovered_order_count}"
    )

    print(
        f"Filled: "
        f"{result.filled_orders}"
    )

    print(
        f"Rejected: "
        f"{result.rejected_orders}"
    )

    print(
        f"Failed: "
        f"{result.failed_orders}"
    )

    print(
        f"Skipped: "
        f"{result.skipped_orders}"
    )

    return (
        1
        if result.failed_orders > 0
        else 0
    )


def run_execution_check_command(
    execution_session: date,
) -> int:

    from trading.execution_readiness import (
        ExecutionReadinessChecker,
        print_readiness,
    )

    checker = (
        ExecutionReadinessChecker()
    )

    result = (
        checker.check(
            execution_session
        )
    )

    print_readiness(
        result
    )

    return (
        0
        if result.ready_to_execute
        else 1
    )


def run_portfolio_command(
    runtime: TradingApplication,
) -> int:

    from evaluation.portfolio_report import (
        print_portfolio_report,
    )

    report = (
        runtime.get_portfolio_report()
    )

    print_portfolio_report(
        report
    )

    return 0


def run_equity_snapshot_command(
    runtime: TradingApplication,
    valuation_session: date,
) -> int:

    result = (
        runtime.record_equity_snapshot(
            valuation_session
        )
    )

    snapshot = (
        result.snapshot
    )

    print()
    print(
        "Equity Snapshot Recorded"
    )

    print(
        "========================"
    )

    print(
        f"Session: "
        f"{snapshot.valuation_session}"
    )

    print(
        f"Equity: "
        f"${snapshot.total_equity:,.2f}"
    )

    print(
        f"Cash: "
        f"${snapshot.cash:,.2f}"
    )

    print(
        f"Market value: "
        f"${snapshot.market_value:,.2f}"
    )

    print(
        f"Total return: "
        f"{snapshot.total_return_pct:.2f}%"
    )

    print(
        f"Exposure: "
        f"{snapshot.exposure_pct:.2f}%"
    )

    print(
        f"Open positions: "
        f"{snapshot.open_positions}"
    )

    return 0


def run_equity_history_command(
    runtime: TradingApplication,
) -> int:

    snapshots = (
        runtime.get_equity_history()
    )

    print()
    print(
        "Equity History"
    )

    print(
        "=============="
    )

    if not snapshots:

        print(
            "No equity snapshots recorded."
        )

        return 0

    print(
        "Session      "
        "Equity        "
        "Return       "
        "Exposure"
    )

    for snapshot in snapshots:

        print(
            f"{snapshot.valuation_session}  "
            f"${snapshot.total_equity:>10,.2f}  "
            f"{snapshot.total_return_pct:>8.2f}%  "
            f"{snapshot.exposure_pct:>8.2f}%"
        )

    return 0


def run_benchmark_command(
    runtime: TradingApplication,
) -> int:

    from evaluation.benchmark import (
        print_benchmark_comparison,
    )

    comparison = (
        runtime.get_benchmark_comparison()
    )

    print_benchmark_comparison(
        comparison
    )

    return 0


def run_equal_weight_benchmark_command(
    runtime: TradingApplication,
) -> int:

    from evaluation.equal_weight_benchmark import (
        print_equal_weight_benchmark,
    )

    comparison = (
        runtime
        .get_equal_weight_benchmark_comparison()
    )

    print_equal_weight_benchmark(
        comparison
    )

    return 0


def run_metrics_command(
    runtime: TradingApplication,
) -> int:

    from evaluation.performance_metrics import (
        print_performance_metrics,
    )

    metrics = (
        runtime.get_performance_metrics()
    )

    print_performance_metrics(
        metrics
    )

    return 0


def run_evaluation_command(
    runtime: TradingApplication,
) -> int:

    from evaluation.evaluation_report import (
        print_evaluation_report,
    )

    report = (
        runtime.get_evaluation_report()
    )

    print_evaluation_report(
        report
    )

    return 0


def run_export_report_command(
    runtime: TradingApplication,
) -> int:

    from evaluation.report_bundle import (
        print_report_bundle_result,
    )

    result = (
        runtime.export_report()
    )

    print_report_bundle_result(
        result
    )

    return 0


def run_status_command(
    runtime: TradingApplication,
) -> int:

    status = (
        runtime.get_status()
    )

    print(
        "Paper Trading Agent Status"
    )

    print(
        "--------------------------"
    )

    print(
        f"Account: "
        f"{status.account_id or 'Not initialized'}"
    )

    if status.starting_cash is not None:

        print(
            f"Starting cash: "
            f"{status.starting_cash}"
        )

    print(
        f"Orders: "
        f"{status.total_orders}"
    )

    print(
        f"  Pending: "
        f"{status.pending_orders}"
    )

    print(
        f"  Filled: "
        f"{status.filled_orders}"
    )

    print(
        f"  Rejected: "
        f"{status.rejected_orders}"
    )

    print(
        f"Fills: "
        f"{status.total_fills}"
    )

    print(
        f"Portfolio snapshots: "
        f"{status.portfolio_snapshots}"
    )

    print(
        f"Execution attempts: "
        f"{status.execution_attempts}"
    )

    return 0


def main(
    argv: Sequence[str] | None = None,
    runtime_factory: (
        Callable[
            [],
            TradingApplication,
        ]
        | None
    ) = None,
) -> int:

    parser = (
        create_parser()
    )

    args = (
        parser.parse_args(
            argv
        )
    )

    try:

        # execution-check intentionally avoids
        # constructing the full runtime.
        if (
            args.command
            == "execution-check"
        ):

            return (
                run_execution_check_command(
                    execution_session=(
                        args.session
                    )
                )
            )

        if runtime_factory is None:

            runtime_factory = (
                build_runtime
            )

        runtime = (
            runtime_factory()
        )

        if (
            args.command
            == "decision"
        ):

            return (
                run_decision_command(
                    runtime=runtime,
                    timestamp=(
                        args.timestamp
                    ),
                )
            )

        if (
            args.command
            == "execution"
        ):

            return (
                run_execution_command(
                    runtime=runtime,
                    execution_session=(
                        args.session
                    ),
                )
            )

        if (
            args.command
            == "portfolio"
        ):

            return (
                run_portfolio_command(
                    runtime
                )
            )

        if (
            args.command
            == "equity-snapshot"
        ):

            return (
                run_equity_snapshot_command(
                    runtime=runtime,
                    valuation_session=(
                        args.session
                    ),
                )
            )

        if (
            args.command
            == "equity-history"
        ):

            return (
                run_equity_history_command(
                    runtime
                )
            )

        if (
            args.command
            == "benchmark"
        ):

            return (
                run_benchmark_command(
                    runtime
                )
            )

        if (
            args.command
            == "equal-weight-benchmark"
        ):

            return (
                run_equal_weight_benchmark_command(
                    runtime
                )
            )

        if (
            args.command
            == "metrics"
        ):

            return (
                run_metrics_command(
                    runtime
                )
            )

        if (
            args.command
            == "evaluation"
        ):

            return (
                run_evaluation_command(
                    runtime
                )
            )

        if (
            args.command
            == "export-report"
        ):

            return (
                run_export_report_command(
                    runtime
                )
            )

        if (
            args.command
            == "status"
        ):

            return (
                run_status_command(
                    runtime
                )
            )

        parser.error(
            "Unknown command."
        )

    except ApplicationRuntimeError as exc:

        print(
            f"ERROR: {exc}",
            file=sys.stderr,
        )

        return 2

    except KeyboardInterrupt:

        print(
            "Operation cancelled.",
            file=sys.stderr,
        )

        return 130

    except Exception as exc:

        print(
            f"ERROR: "
            f"{type(exc).__name__}: "
            f"{exc}",
            file=sys.stderr,
        )

        return 1

    return 0


if __name__ == "__main__":

    raise SystemExit(
        main()
    )