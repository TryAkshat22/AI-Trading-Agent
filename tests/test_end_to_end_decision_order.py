from __future__ import annotations

from datetime import (
    date,
    datetime,
    timezone,
)
from decimal import Decimal

import pandas as pd

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
    ExecutionService,
)
from trading.orders import (
    OrderSide,
    OrderStatus,
)
from trading.paper_broker import (
    BrokerConfig,
)


def make_bullish_market_result(
) -> MarketDataResult:
    """
    Create enough steadily rising price history
    to satisfy Model 1's SMA and momentum filters.

    The final completed session is
    Friday, September 4, 2026.
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

            # Historical indicators use
            # adjusted prices.
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
        provider="integration-test",
        retrieved_at_utc=datetime(
            2026,
            9,
            4,
            21,
            5,
            tzinfo=timezone.utc,
        ),
    )


def make_safe_quality_report(
) -> DataQualityReport:
    """
    Represent a completed and approved
    September 4 decision snapshot.
    """

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


def test_real_bullish_decision_creates_traceable_pending_order(
    tmp_path,
):
    """
    Full decision-to-order integration test.

    Verifies:

        market data
            ↓
        persisted ingestion run
            ↓
        real DecisionPipeline
            ↓
        BUY_APPROVED
            ↓
        real timestamp validation
            ↓
        real coordinator
            ↓
        real ExecutionService
            ↓
        persistent PENDING SQLite order

    No fill is executed in this test.
    """

    database_path = (
        tmp_path
        / "test.db"
    )

    # -----------------------------------------
    # REAL STORAGE
    # -----------------------------------------

    accounts = AccountStorage(
        database_path
    )

    trades = TradingStorage(
        database_path
    )

    market_storage = (
        MarketDataStorage(
            database_path
        )
    )

    accounts.initialize()
    trades.initialize()
    market_storage.initialize()

    accounts.create_account(
        10_000
    )

    # -----------------------------------------
    # REAL DECISION PIPELINE
    # -----------------------------------------

    decision_pipeline = (
        DecisionPipeline(
            account_storage=accounts,
            trading_storage=trades,
        )
    )

    # -----------------------------------------
    # REAL EXECUTION PREPARATION LAYER
    # -----------------------------------------

    execution_service = (
        ExecutionService(
            account_storage=accounts,
            trading_storage=trades,

            # Execution is not performed here,
            # but keep broker assumptions explicit.
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

    # -----------------------------------------
    # INPUT DATA
    # -----------------------------------------

    market_result = (
        make_bullish_market_result()
    )

    quality_report = (
        make_safe_quality_report()
    )

    latest_raw_close = Decimal(
        str(
            market_result
            .data["Close"]
            .iloc[-1]
        )
    )

    # Friday September 4 NYSE closes
    # at 20:00 UTC.
    #
    # 21:00 UTC is safely after close.
    #
    # Monday September 7 is Labor Day,
    # therefore the next valid execution
    # session is Tuesday September 8.
    decision_timestamp = datetime(
        2026,
        9,
        4,
        21,
        0,
        tzinfo=timezone.utc,
    )

    # -----------------------------------------
    # RUN THE REAL DAILY DECISION CYCLE
    # -----------------------------------------

    result = orchestrator.run(
        market_result=(
            market_result
        ),
        quality_report=(
            quality_report
        ),
        decision_timestamp=(
            decision_timestamp
        ),

        # DecisionPipeline uses current prices
        # for portfolio/risk valuation.
        decision_kwargs={
            "market_prices": {
                "AAPL": (
                    latest_raw_close
                ),
            },
        },

        order_id=(
            "e2e-buy-order"
        ),
    )

    # -----------------------------------------
    # DECISION ASSERTIONS
    # -----------------------------------------

    assert (
        result.decision.status
        == DecisionStatus.BUY_APPROVED
    )

    assert (
        result.decision.side
        == OrderSide.BUY
    )

    assert (
        result.decision.quantity
        is not None
    )

    assert (
        result.decision.quantity
        > 0
    )

    # -----------------------------------------
    # COORDINATOR ASSERTIONS
    # -----------------------------------------

    assert (
        result.order_created
    )

    assert (
        result.prepared_order
        is not None
    )

    assert (
        result.prepared_order
        .order.order_id
        == "e2e-buy-order"
    )

    assert (
        result.prepared_order
        .order.side
        == OrderSide.BUY
    )

    assert (
        result.prepared_order
        .order.quantity
        == result.decision.quantity
    )

    # Labor Day weekend must be respected.
    assert (
        result.prepared_order
        .order.execution_session
        == date(
            2026,
            9,
            8,
        )
    )

    # -----------------------------------------
    # DATABASE ASSERTIONS
    # -----------------------------------------

    assert (
        market_storage
        .count_ingestion_runs()
        == 1
    )

    assert (
        trades.count_orders()
        == 1
    )

    assert (
        trades.count_fills()
        == 0
    )

    assert (
        trades.get_order_status(
            "e2e-buy-order"
        )
        == OrderStatus.PENDING.value
    )

    stored_order = (
        trades.get_order(
            "e2e-buy-order"
        )
    )

    assert (
        stored_order is not None
    )

    # -----------------------------------------
    # LINEAGE ASSERTIONS
    # -----------------------------------------

    assert (
        result.decision_run_id
        is not None
    )

    assert (
        stored_order.decision_run_id
        == result.decision_run_id
    )

    assert (
        stored_order.model_version
        == "model-1-integration"
    )

    # New explicit lineage should be used,
    # rather than relying on the ambiguous
    # legacy source_run_id column.
    assert (
        stored_order.source_run_id
        is None
    )

    # -----------------------------------------
    # ANTI-LOOKAHEAD ASSERTIONS
    # -----------------------------------------

    validated = (
        result.coordinated
        .validated_timestamp
    )

    assert (
        validated is not None
    )

    assert (
        validated.source_session
        == date(
            2026,
            9,
            4,
        )
    )

    assert (
        validated.next_execution_session
        == date(
            2026,
            9,
            8,
        )
    )

    assert (
        validated
        .decision_timestamp_utc
        >= validated.source_close_utc
    )

    assert (
        validated
        .decision_timestamp_utc
        < validated
        .next_execution_open_utc
    )