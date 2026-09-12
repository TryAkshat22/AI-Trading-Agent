from __future__ import annotations

from datetime import (
    date,
    datetime,
    timezone,
)
from decimal import Decimal

import pandas as pd
import pytest

from database.account_storage import (
    AccountStorage,
)
from database.storage import (
    MarketDataStorage,
)
from database.trading_storage import (
    TradingStorage,
)
from services.data_quality import (
    DataQualityReport,
)
from services.market_data import (
    MarketDataResult,
)
from trading.daily_decision_orchestrator import (
    DailyDecisionOrchestrator,
)
from trading.decision_execution_coordinator import (
    DecisionExecutionCoordinator,
)
from trading.decision_pipeline import (
    DecisionPipeline,
    DecisionStatus,
)
from trading.execution_service import (
    ExecutionRiskRejectedError,
    ExecutionService,
)
from trading.orders import (
    OrderSide,
    OrderStatus,
)
from trading.paper_broker import (
    BrokerConfig,
)


# =========================================================
# DECISION-SIDE TEST DATA
# =========================================================


def make_bullish_decision_market_result(
) -> MarketDataResult:
    """
    Create strongly bullish historical data ending on
    Friday, September 4, 2026.

    The real DecisionPipeline should approve a BUY.
    """

    dates = pd.bdate_range(
        end="2026-09-04",
        periods=80,
    )

    closes = [
        80.0 + index
        for index in range(
            len(dates)
        )
    ]

    data = pd.DataFrame(
        {
            "Open": [
                price - 0.50
                for price in closes
            ],
            "High": [
                price + 1.00
                for price in closes
            ],
            "Low": [
                price - 1.00
                for price in closes
            ],
            "Close": closes,
            "Adj Close": closes,
            "Volume": [
                1_000_000
                for _ in closes
            ],
        },
        index=dates,
    )

    return MarketDataResult(
        ticker="AAPL",
        data=data,
        provider="integration-decision",
        retrieved_at_utc=datetime(
            2026,
            9,
            4,
            21,
            5,
            tzinfo=timezone.utc,
        ),
    )


def make_decision_quality_report(
) -> DataQualityReport:

    return DataQualityReport(
        ticker="AAPL",
        checked_at_utc=datetime(
            2026,
            9,
            4,
            21,
            6,
            tzinfo=timezone.utc,
        ),
        latest_data_session=date(
            2026,
            9,
            4,
        ),
        latest_expected_completed_session=date(
            2026,
            9,
            4,
        ),
        issues=(),
    )


# =========================================================
# EXECUTION-SIDE TEST DATA
# =========================================================


def make_execution_market_result(
    open_price: float,
) -> MarketDataResult:
    """
    Create the execution-session observation for
    Tuesday, September 8, 2026.

    September 7 was Labor Day, so September 8 is the
    correct next NYSE session after September 4.
    """

    data = pd.DataFrame(
        {
            "Open": [
                open_price
            ],
            "High": [
                open_price + 5.0
            ],
            "Low": [
                max(
                    open_price - 5.0,
                    0.01,
                )
            ],
            "Close": [
                open_price + 2.0
            ],
            "Adj Close": [
                open_price + 2.0
            ],
            "Volume": [
                1_000_000
            ],
        },
        index=pd.to_datetime(
            [
                "2026-09-08",
            ]
        ),
    )

    return MarketDataResult(
        ticker="AAPL",
        data=data,
        provider="integration-execution",
        retrieved_at_utc=datetime(
            2026,
            9,
            8,
            20,
            0,
            tzinfo=timezone.utc,
        ),
    )


def make_execution_quality_report(
) -> DataQualityReport:

    return DataQualityReport(
        ticker="AAPL",
        checked_at_utc=datetime(
            2026,
            9,
            8,
            20,
            1,
            tzinfo=timezone.utc,
        ),
        latest_data_session=date(
            2026,
            9,
            8,
        ),
        latest_expected_completed_session=date(
            2026,
            9,
            8,
        ),
        issues=(),
    )


# =========================================================
# REAL SYSTEM SETUP
# =========================================================


def make_real_system(
    tmp_path,
):
    """
    Build the real Model 1 decision/execution stack
    against one temporary SQLite database.
    """

    database_path = (
        tmp_path
        / "test.db"
    )

    accounts = AccountStorage(
        database_path
    )

    market_storage = (
        MarketDataStorage(
            database_path
        )
    )

    trades = TradingStorage(
        database_path
    )

    accounts.initialize()
    market_storage.initialize()
    trades.initialize()

    accounts.create_account(
        10_000
    )

    decision_pipeline = (
        DecisionPipeline(
            account_storage=accounts,
            trading_storage=trades,
        )
    )

    execution_service = (
        ExecutionService(
            account_storage=accounts,
            trading_storage=trades,
            broker_config=BrokerConfig(
                slippage_bps=Decimal(
                    "5"
                ),
                fee_per_trade=Decimal(
                    "0"
                ),
            ),
        )
    )

    coordinator = (
        DecisionExecutionCoordinator(
            execution_service=(
                execution_service
            )
        )
    )

    orchestrator = (
        DailyDecisionOrchestrator(
            market_storage=(
                market_storage
            ),
            decision_pipeline=(
                decision_pipeline
            ),
            coordinator=(
                coordinator
            ),
            model_version=(
                "model-1-integration"
            ),
        )
    )

    return (
        accounts,
        market_storage,
        trades,
        execution_service,
        orchestrator,
    )


def create_real_pending_buy(
    market_storage,
    trades,
    orchestrator,
    order_id: str,
):
    """
    Run the complete real decision cycle and leave
    behind a persistent PENDING BUY order.
    """

    market_result = (
        make_bullish_decision_market_result()
    )

    decision_close = Decimal(
        str(
            market_result
            .data[
                "Close"
            ]
            .iloc[-1]
        )
    )

    result = orchestrator.run(
        market_result=(
            market_result
        ),
        quality_report=(
            make_decision_quality_report()
        ),
        decision_timestamp=datetime(
            2026,
            9,
            4,
            21,
            0,
            tzinfo=timezone.utc,
        ),
        decision_kwargs={
            "market_prices": {
                "AAPL": (
                    decision_close
                ),
            },
        },
        order_id=order_id,
    )

    assert (
        result.decision.status
        == DecisionStatus.BUY_APPROVED
    )

    assert (
        result.decision.side
        == OrderSide.BUY
    )

    assert result.order_created

    assert (
        trades.get_order_status(
            order_id
        )
        == OrderStatus.PENDING.value
    )

    assert (
        market_storage
        .count_ingestion_runs()
        == 1
    )

    return result


# =========================================================
# SUCCESS PATH
# =========================================================


def test_pending_order_executes_with_execution_lineage(
    tmp_path,
):
    """
    Real end-to-end success path:

        decision snapshot
            ↓
        BUY_APPROVED
            ↓
        PENDING order
            ↓
        next-session execution snapshot
            ↓
        raw Open
            ↓
        execution-time risk
            ↓
        broker fill
            ↓
        FILLED
            ↓
        execution_run_id
            ↓
        portfolio snapshot
    """

    (
        _,
        market_storage,
        trades,
        execution_service,
        orchestrator,
    ) = make_real_system(
        tmp_path
    )

    decision_result = (
        create_real_pending_buy(
            market_storage=(
                market_storage
            ),
            trades=trades,
            orchestrator=orchestrator,
            order_id=(
                "e2e-fill-order"
            ),
        )
    )

    decision_run_id = (
        decision_result
        .decision_run_id
    )

    # -------------------------------------------------
    # PERSIST EXECUTION OBSERVATION
    # -------------------------------------------------

    execution_market_result = (
        make_execution_market_result(
            open_price=160.0
        )
    )

    execution_quality_report = (
        make_execution_quality_report()
    )

    execution_snapshot = (
        market_storage
        .save_market_snapshot(
            result=(
                execution_market_result
            ),
            quality_report=(
                execution_quality_report
            ),
        )
    )

    execution_run_id = (
        execution_snapshot.run_id
    )

    # Decision and execution observations must
    # never collapse into the same lineage ID.
    assert (
        execution_run_id
        != decision_run_id
    )

    # -------------------------------------------------
    # EXECUTE REAL PENDING ORDER
    # -------------------------------------------------

    executed = (
        execution_service
        .execute_order(
            order_id=(
                "e2e-fill-order"
            ),
            market_result=(
                execution_market_result
            ),
            quality_report=(
                execution_quality_report
            ),
            execution_run_id=(
                execution_run_id
            ),
            valuation_prices={
                "AAPL": Decimal(
                    "160"
                ),
            },
            recorded_at_utc=datetime(
                2026,
                9,
                8,
                20,
                30,
                tzinfo=timezone.utc,
            ),
        )
    )

    # -------------------------------------------------
    # EXECUTION ASSERTIONS
    # -------------------------------------------------

    assert (
        executed
        .execution_risk_assessment
        .approved
    )

    assert (
        executed.fill.order_id
        == "e2e-fill-order"
    )

    assert (
        executed.fill.side
        == OrderSide.BUY
    )

    assert (
        executed.fill.execution_session
        == date(
            2026,
            9,
            8,
        )
    )

    # -------------------------------------------------
    # DATABASE STATE
    # -------------------------------------------------

    assert (
        trades.get_order_status(
            "e2e-fill-order"
        )
        == OrderStatus.FILLED.value
    )

    assert (
        trades.count_orders()
        == 1
    )

    assert (
        trades.count_fills()
        == 1
    )

    assert (
        trades.count_portfolio_snapshots()
        == 1
    )

    assert (
        executed.portfolio_snapshot_id
        is not None
    )

    # Two immutable market observations now exist:
    #
    # 1. decision snapshot
    # 2. execution snapshot
    assert (
        market_storage
        .count_ingestion_runs()
        == 2
    )

    # -------------------------------------------------
    # DECISION LINEAGE
    # -------------------------------------------------

    stored_order = (
        trades.get_order(
            "e2e-fill-order"
        )
    )

    assert stored_order is not None

    assert (
        stored_order.decision_run_id
        == decision_run_id
    )

    # -------------------------------------------------
    # EXECUTION LINEAGE
    # -------------------------------------------------

    fills = (
        trades.list_fills()
    )

    assert (
        len(fills)
        == 1
    )

    stored_fill = (
        fills[0]
    )

    assert (
        stored_fill.execution_run_id
        == execution_run_id
    )

    # The two provenance links must remain
    # independently traceable.
    assert (
        stored_order.decision_run_id
        != stored_fill.execution_run_id
    )


# =========================================================
# FAIL-CLOSED PATH
# =========================================================


def test_overnight_gap_rejects_real_pending_order(
    tmp_path,
):
    """
    Real fail-closed execution path.

    The order was valid around the decision-session
    close, but an extreme overnight gap makes the
    position unsafe at the next raw Open.

    No fill may be created.
    """

    (
        _,
        market_storage,
        trades,
        execution_service,
        orchestrator,
    ) = make_real_system(
        tmp_path
    )

    decision_result = (
        create_real_pending_buy(
            market_storage=(
                market_storage
            ),
            trades=trades,
            orchestrator=orchestrator,
            order_id=(
                "e2e-gap-reject"
            ),
        )
    )

    decision_run_id = (
        decision_result
        .decision_run_id
    )

    # -------------------------------------------------
    # EXTREME EXECUTION OPEN
    # -------------------------------------------------

    execution_market_result = (
        make_execution_market_result(
            open_price=2_000.0
        )
    )

    execution_quality_report = (
        make_execution_quality_report()
    )

    execution_snapshot = (
        market_storage
        .save_market_snapshot(
            result=(
                execution_market_result
            ),
            quality_report=(
                execution_quality_report
            ),
        )
    )

    execution_run_id = (
        execution_snapshot.run_id
    )

    assert (
        execution_run_id
        != decision_run_id
    )

    # -------------------------------------------------
    # EXECUTION MUST FAIL CLOSED
    # -------------------------------------------------

    with pytest.raises(
        ExecutionRiskRejectedError
    ):
        execution_service.execute_order(
            order_id=(
                "e2e-gap-reject"
            ),
            market_result=(
                execution_market_result
            ),
            quality_report=(
                execution_quality_report
            ),
            execution_run_id=(
                execution_run_id
            ),
        )

    # -------------------------------------------------
    # REJECTION MUST BE PERSISTENT
    # -------------------------------------------------

    assert (
        trades.get_order_status(
            "e2e-gap-reject"
        )
        == OrderStatus.REJECTED.value
    )

    assert (
        trades.count_orders()
        == 1
    )

    assert (
        trades.count_fills()
        == 0
    )

    rejection = (
        trades.get_order_rejection(
            "e2e-gap-reject"
        )
    )

    assert (
        rejection is not None
    )

    # No successful execution means there should
    # be no portfolio snapshot for this order.
    assert (
        trades.count_portfolio_snapshots()
        == 0
    )

    # Both observations still remain persisted:
    # rejection must not erase evidence.
    assert (
        market_storage
        .count_ingestion_runs()
        == 2
    )

    # Original decision lineage must remain intact.
    stored_order = (
        trades.get_order(
            "e2e-gap-reject"
        )
    )

    assert stored_order is not None

    assert (
        stored_order.decision_run_id
        == decision_run_id
    )