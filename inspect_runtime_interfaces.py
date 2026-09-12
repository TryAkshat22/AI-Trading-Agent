from __future__ import annotations

import inspect


def show_object(
    label: str,
    obj,
) -> None:

    print()
    print("=" * 78)
    print(label)
    print("=" * 78)

    try:
        print(
            "Signature:",
            inspect.signature(
                obj
            ),
        )
    except Exception as exc:
        print(
            "Signature unavailable:",
            type(exc).__name__,
            str(exc),
        )


def show_class(
    label: str,
    cls,
    methods: list[str],
) -> None:

    show_object(
        label,
        cls,
    )

    for method_name in methods:

        print()

        if not hasattr(
            cls,
            method_name,
        ):
            print(
                f"{method_name}: "
                "NOT FOUND"
            )
            continue

        method = getattr(
            cls,
            method_name,
        )

        try:
            signature = (
                inspect.signature(
                    method
                )
            )

            print(
                f"{method_name}"
                f"{signature}"
            )

        except Exception as exc:

            print(
                f"{method_name}: "
                "SIGNATURE ERROR "
                f"{type(exc).__name__}: "
                f"{exc}"
            )


def main() -> None:

    print()
    print(
        "PaperTradingAgent "
        "Runtime Interface Inspection"
    )

    # ==========================================================
    # MARKET DATA
    # ==========================================================

    from services.market_data import (
        YahooFinanceProvider,
        get_market_data,
    )

    show_class(
        "YahooFinanceProvider",
        YahooFinanceProvider,
        [
            "get_daily_history",
        ],
    )

    show_object(
        "get_market_data",
        get_market_data,
    )

    # ==========================================================
    # DATA QUALITY
    # ==========================================================

    from services.data_quality import (
        MarketDataQualityValidator,
    )

    show_class(
        "MarketDataQualityValidator",
        MarketDataQualityValidator,
        [
            "validate",
        ],
    )

    # ==========================================================
    # DATABASE
    # ==========================================================

    from database.storage import (
        MarketDataStorage,
        get_default_database_path,
    )

    show_class(
        "MarketDataStorage",
        MarketDataStorage,
        [
            "initialize",
            "save_market_snapshot",
            "count_ingestion_runs",
            "count_market_bars",
        ],
    )

    show_object(
        "get_default_database_path",
        get_default_database_path,
    )

    from database.account_storage import (
        AccountStorage,
    )

    show_class(
        "AccountStorage",
        AccountStorage,
        [
            "initialize",
            "create_account",
            "get_account",
            "get_or_create",
            "count_accounts",
        ],
    )

    from database.trading_storage import (
        TradingStorage,
    )

    show_class(
        "TradingStorage",
        TradingStorage,
        [
            "initialize",
            "save_order",
            "save_fill",
            "reject_order",
            "get_order",
            "get_order_status",
            "list_fills",
            "count_orders",
            "count_fills",
            "count_portfolio_snapshots",
        ],
    )

    from database.execution_attempt_storage import (
        ExecutionAttemptStorage,
    )

    show_class(
        "ExecutionAttemptStorage",
        ExecutionAttemptStorage,
        [
            "initialize",
            "start_attempt",
            "finalize_attempt",
            "get_attempt",
            "list_attempts_for_order",
            "count_attempts",
        ],
    )

    from database.pending_order_query import (
        PendingOrderQuery,
    )

    show_class(
        "PendingOrderQuery",
        PendingOrderQuery,
        [
            "find_for_session",
            "find_order_ids_for_session",
            "count_for_session",
        ],
    )

    # ==========================================================
    # SIGNAL / RISK
    # ==========================================================

    from signals.signal_engine import (
        SignalEngine,
    )

    show_class(
        "SignalEngine",
        SignalEngine,
        [
            "evaluate",
            "generate",
        ],
    )

    from risk.risk_engine import (
        RiskEngine,
    )

    show_class(
        "RiskEngine",
        RiskEngine,
        [
            "assess",
        ],
    )

    from risk.position_sizer import (
        PositionSizer,
    )

    show_class(
        "PositionSizer",
        PositionSizer,
        [
            "size",
            "calculate",
        ],
    )

    # ==========================================================
    # DECISION SIDE
    # ==========================================================

    from trading.decision_pipeline import (
        DecisionPipeline,
    )

    show_class(
        "DecisionPipeline",
        DecisionPipeline,
        [
            "evaluate",
        ],
    )

    from trading.execution_service import (
        ExecutionService,
    )

    show_class(
        "ExecutionService",
        ExecutionService,
        [
            "prepare_order",
            "execute_order",
        ],
    )

    from trading.decision_execution_coordinator import (
        DecisionExecutionCoordinator,
    )

    show_class(
        "DecisionExecutionCoordinator",
        DecisionExecutionCoordinator,
        [
            "coordinate",
        ],
    )

    from trading.daily_decision_orchestrator import (
        DailyDecisionOrchestrator,
    )

    show_class(
        "DailyDecisionOrchestrator",
        DailyDecisionOrchestrator,
        [
            "run",
        ],
    )

    from trading.daily_batch_runner import (
        DailyBatchRunner,
    )

    show_class(
        "DailyBatchRunner",
        DailyBatchRunner,
        [
            "run",
        ],
    )

    from trading.daily_decision_runner import (
        DailyDecisionRunner,
    )

    show_class(
        "DailyDecisionRunner",
        DailyDecisionRunner,
        [
            "run",
        ],
    )

    # ==========================================================
    # EXECUTION SIDE
    # ==========================================================

    from trading.execution_observation import (
        ExecutionObservationValidator,
    )

    show_class(
        "ExecutionObservationValidator",
        ExecutionObservationValidator,
        [
            "validate",
        ],
    )

    from trading.execution_orchestrator import (
        ExecutionOrchestrator,
    )

    show_class(
        "ExecutionOrchestrator",
        ExecutionOrchestrator,
        [
            "execute",
        ],
    )

    from trading.pending_execution_batch_runner import (
        PendingExecutionBatchRunner,
    )

    show_class(
        "PendingExecutionBatchRunner",
        PendingExecutionBatchRunner,
        [
            "run",
        ],
    )

    from trading.daily_execution_runner import (
        DailyExecutionRunner,
    )

    show_class(
        "DailyExecutionRunner",
        DailyExecutionRunner,
        [
            "run",
        ],
    )

    print()
    print("=" * 78)
    print(
        "INSPECTION COMPLETE"
    )
    print("=" * 78)
    print()


if __name__ == "__main__":
    main()