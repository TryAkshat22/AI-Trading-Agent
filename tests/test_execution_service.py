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
from database.trading_storage import (
    TradingStorage,
)
from services.data_quality import (
    DataQualityReport,
)
from services.market_data import (
    MarketDataResult,
)
from trading.execution_service import (
    ExecutionRiskRejectedError,
    ExecutionService,
    OrderNotPendingError,
    PendingOrderNotFoundError,
)
from trading.orders import (
    OrderSide,
    OrderStatus,
)
from trading.paper_broker import (
    BrokerConfig,
)


def make_market_result(
    ticker: str = "AAPL",
    open_price: float = 100.0,
) -> MarketDataResult:

    data = pd.DataFrame(
        {
            "Open": [
                open_price,
            ],
            "High": [
                open_price + 5,
            ],
            "Low": [
                open_price - 5,
            ],
            "Close": [
                open_price + 2,
            ],
            "Adj Close": [
                open_price + 2,
            ],
            "Volume": [
                1_000_000,
            ],
        },
        index=pd.to_datetime(
            [
                "2026-09-08",
            ]
        ),
    )

    return MarketDataResult(
        ticker=ticker,
        data=data,
        provider="test",
        retrieved_at_utc=datetime(
            2026,
            9,
            8,
            20,
            0,
            tzinfo=timezone.utc,
        ),
    )


def make_quality_report(
    ticker: str = "AAPL",
) -> DataQualityReport:

    return DataQualityReport(
        ticker=ticker,
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


def make_service(
    tmp_path,
    slippage_bps=Decimal("0"),
):

    db = (
        tmp_path
        / "test.db"
    )

    accounts = AccountStorage(
        db
    )

    trades = TradingStorage(
        db
    )

    accounts.initialize()
    trades.initialize()

    accounts.create_account(
        10_000
    )

    service = ExecutionService(
        account_storage=accounts,
        trading_storage=trades,
        broker_config=BrokerConfig(
            slippage_bps=(
                slippage_bps
            ),
            fee_per_trade=Decimal(
                "0"
            ),
        ),
    )

    return (
        db,
        accounts,
        trades,
        service,
    )


def test_prepare_order_persists_pending_order(
    tmp_path,
):

    _, _, trades, service = (
        make_service(
            tmp_path
        )
    )

    prepared = service.prepare_order(
        ticker="AAPL",
        side=OrderSide.BUY,

        # $500 at a $100 reference price,
        # safely below the default position cap.
        quantity=5,

        signal_timestamp=datetime(
            2026,
            9,
            4,
            21,
            0,
            tzinfo=timezone.utc,
        ),
        order_id="order-1",
    )

    assert (
        prepared.order.order_id
        == "order-1"
    )

    assert (
        trades.count_orders()
        == 1
    )

    assert (
        trades.get_order_status(
            "order-1"
        )
        == OrderStatus.PENDING.value
    )


def test_execution_persists_fill(
    tmp_path,
):

    _, _, trades, service = (
        make_service(
            tmp_path
        )
    )

    service.prepare_order(
        ticker="AAPL",
        side=OrderSide.BUY,
        quantity=5,
        signal_timestamp=datetime(
            2026,
            9,
            4,
            21,
            0,
            tzinfo=timezone.utc,
        ),
        order_id="order-1",
    )

    executed = service.execute_order(
        order_id="order-1",
        market_result=(
            make_market_result()
        ),
        quality_report=(
            make_quality_report()
        ),
    )

    assert (
        executed.fill.order_id
        == "order-1"
    )

    assert (
        trades.count_fills()
        == 1
    )

    assert (
        trades.get_order_status(
            "order-1"
        )
        == OrderStatus.FILLED.value
    )


def test_same_order_cannot_execute_twice(
    tmp_path,
):

    _, _, trades, service = (
        make_service(
            tmp_path
        )
    )

    service.prepare_order(
        ticker="AAPL",
        side=OrderSide.BUY,
        quantity=5,
        signal_timestamp=datetime(
            2026,
            9,
            4,
            21,
            0,
            tzinfo=timezone.utc,
        ),
        order_id="order-1",
    )

    service.execute_order(
        order_id="order-1",
        market_result=(
            make_market_result()
        ),
        quality_report=(
            make_quality_report()
        ),
    )

    with pytest.raises(
        OrderNotPendingError
    ):
        service.execute_order(
            order_id="order-1",
            market_result=(
                make_market_result()
            ),
            quality_report=(
                make_quality_report()
            ),
        )

    assert (
        trades.count_fills()
        == 1
    )


def test_unknown_order_is_rejected(
    tmp_path,
):

    _, _, _, service = (
        make_service(
            tmp_path
        )
    )

    with pytest.raises(
        PendingOrderNotFoundError
    ):
        service.execute_order(
            order_id=(
                "does-not-exist"
            ),
            market_result=(
                make_market_result()
            ),
            quality_report=(
                make_quality_report()
            ),
        )


def test_portfolio_snapshot_is_created(
    tmp_path,
):

    _, _, trades, service = (
        make_service(
            tmp_path
        )
    )

    service.prepare_order(
        ticker="AAPL",
        side=OrderSide.BUY,
        quantity=5,
        signal_timestamp=datetime(
            2026,
            9,
            4,
            21,
            0,
            tzinfo=timezone.utc,
        ),
        order_id="order-1",
    )

    executed = service.execute_order(
        order_id="order-1",
        market_result=(
            make_market_result()
        ),
        quality_report=(
            make_quality_report()
        ),
        valuation_prices={
            "AAPL": Decimal(
                "100"
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

    assert (
        executed.portfolio_snapshot_id
        is not None
    )

    assert (
        trades
        .count_portfolio_snapshots()
        == 1
    )


def test_service_survives_restart(
    tmp_path,
):

    db, _, _, service = (
        make_service(
            tmp_path
        )
    )

    service.prepare_order(
        ticker="AAPL",
        side=OrderSide.BUY,
        quantity=5,
        signal_timestamp=datetime(
            2026,
            9,
            4,
            21,
            0,
            tzinfo=timezone.utc,
        ),
        order_id="order-1",
    )

    restarted_accounts = (
        AccountStorage(
            db
        )
    )

    restarted_trades = (
        TradingStorage(
            db
        )
    )

    restarted_accounts.initialize()
    restarted_trades.initialize()

    restarted_service = (
        ExecutionService(
            account_storage=(
                restarted_accounts
            ),
            trading_storage=(
                restarted_trades
            ),
            broker_config=(
                BrokerConfig(
                    slippage_bps=Decimal(
                        "0"
                    ),
                    fee_per_trade=Decimal(
                        "0"
                    ),
                )
            ),
        )
    )

    restarted_service.execute_order(
        order_id="order-1",
        market_result=(
            make_market_result()
        ),
        quality_report=(
            make_quality_report()
        ),
    )

    assert (
        restarted_trades
        .count_fills()
        == 1
    )

    assert (
        restarted_trades
        .get_order_status(
            "order-1"
        )
        == OrderStatus.FILLED.value
    )


def test_execution_time_risk_approves_safe_trade(
    tmp_path,
):

    _, _, trades, service = (
        make_service(
            tmp_path
        )
    )

    service.prepare_order(
        ticker="AAPL",
        side=OrderSide.BUY,
        quantity=5,
        signal_timestamp=datetime(
            2026,
            9,
            4,
            21,
            0,
            tzinfo=timezone.utc,
        ),
        order_id="safe-order",
    )

    executed = service.execute_order(
        order_id="safe-order",
        market_result=(
            make_market_result(
                open_price=100.0
            )
        ),
        quality_report=(
            make_quality_report()
        ),
    )

    assert (
        executed
        .execution_risk_assessment
        .approved
    )

    assert (
        trades.count_fills()
        == 1
    )

    assert (
        trades.get_order_status(
            "safe-order"
        )
        == OrderStatus.FILLED.value
    )


def test_overnight_gap_can_reject_order(
    tmp_path,
):

    _, _, trades, service = (
        make_service(
            tmp_path
        )
    )

    # 5 shares is safe near $100:
    # approximately $500.
    service.prepare_order(
        ticker="AAPL",
        side=OrderSide.BUY,
        quantity=5,
        signal_timestamp=datetime(
            2026,
            9,
            4,
            21,
            0,
            tzinfo=timezone.utc,
        ),
        order_id="gap-reject",
    )

    # Next-session raw Open becomes $2,000.
    #
    # Five shares would now create an
    # approximately $10,000 position,
    # violating the normal risk limits.
    with pytest.raises(
        ExecutionRiskRejectedError
    ):
        service.execute_order(
            order_id="gap-reject",
            market_result=(
                make_market_result(
                    open_price=2_000.0
                )
            ),
            quality_report=(
                make_quality_report()
            ),
        )

    assert (
        trades.count_fills()
        == 0
    )

    assert (
        trades.get_order_status(
            "gap-reject"
        )
        == OrderStatus.REJECTED.value
    )

    rejection = (
        trades.get_order_rejection(
            "gap-reject"
        )
    )

    assert (
        rejection is not None
    )


def test_execution_risk_includes_slippage(
    tmp_path,
):

    # Instead of constructing RiskConfig
    # with implementation-specific field names,
    # use the production defaults and create a
    # sufficiently large slippage shock.
    _, _, trades, service = (
        make_service(
            tmp_path,
            slippage_bps=Decimal(
                "20000"
            ),
        )
    )

    # At raw $100:
    #
    # 5 shares = $500 and normally safe.
    #
    # 20,000 bps BUY slippage = +200%.
    # Projected fill = $300/share.
    #
    # Projected position = $1,500,
    # which exceeds the normal 10%
    # per-position allocation on $10,000.
    service.prepare_order(
        ticker="AAPL",
        side=OrderSide.BUY,
        quantity=5,
        signal_timestamp=datetime(
            2026,
            9,
            4,
            21,
            0,
            tzinfo=timezone.utc,
        ),
        order_id="slippage-order",
    )

    with pytest.raises(
        ExecutionRiskRejectedError
    ):
        service.execute_order(
            order_id=(
                "slippage-order"
            ),
            market_result=(
                make_market_result(
                    open_price=100.0
                )
            ),
            quality_report=(
                make_quality_report()
            ),
        )

    assert (
        trades.count_fills()
        == 0
    )

    assert (
        trades.get_order_status(
            "slippage-order"
        )
        == OrderStatus.REJECTED.value
    )