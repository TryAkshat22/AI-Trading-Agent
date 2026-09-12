from __future__ import annotations

from datetime import (
    date,
    datetime,
    timezone,
)

from audit_pending_orders import (
    PendingOrderAuditor,
)
from database.account_storage import (
    AccountStorage,
)
from database.execution_attempt_storage import (
    ExecutionAttemptStorage,
)
from database.storage import (
    MarketDataStorage,
)
from database.trading_storage import (
    TradingStorage,
)
from trading.execution_service import (
    ExecutionService,
)
from trading.orders import (
    OrderSide,
)


SESSION = date(
    2026,
    9,
    14,
)


def build_environment(
    tmp_path,
):

    db = (
        tmp_path
        / "audit.db"
    )

    market = (
        MarketDataStorage(
            db
        )
    )

    accounts = (
        AccountStorage(
            db
        )
    )

    trades = (
        TradingStorage(
            db
        )
    )

    attempts = (
        ExecutionAttemptStorage(
            db
        )
    )

    market.initialize()
    accounts.initialize()
    trades.initialize()
    attempts.initialize()

    accounts.get_or_create(
        starting_cash=10_000
    )

    service = (
        ExecutionService(
            account_storage=accounts,
            trading_storage=trades,
        )
    )

    return (
        db,
        trades,
        attempts,
        service,
    )


def create_pending_order(
    service,
    *,
    order_id: str,
    ticker: str = "AAPL",
):

    return (
        service.prepare_order(
            ticker=ticker,
            side=OrderSide.BUY,
            quantity=1,
            signal_timestamp=datetime(
                2026,
                9,
                11,
                21,
                0,
                tzinfo=timezone.utc,
            ),
            model_version="model-1",
            decision_run_id=None,
            order_id=order_id,
        )
    )


def test_pending_order_is_found(
    tmp_path,
):

    (
        db,
        _,
        _,
        service,
    ) = build_environment(
        tmp_path
    )

    create_pending_order(
        service,
        order_id="order-1",
    )

    auditor = (
        PendingOrderAuditor(
            db
        )
    )

    result = (
        auditor.audit_session(
            SESSION
        )
    )

    assert (
        result.total_orders
        == 1
    )

    assert (
        result.records[0]
        .ticker
        == "AAPL"
    )


def test_existing_fill_count_defaults_zero(
    tmp_path,
):

    (
        db,
        _,
        _,
        service,
    ) = build_environment(
        tmp_path
    )

    create_pending_order(
        service,
        order_id="order-1",
    )

    result = (
        PendingOrderAuditor(
            db
        )
        .audit_session(
            SESSION
        )
    )

    assert (
        result.records[0]
        .fill_count
        == 0
    )


def test_existing_attempt_count_defaults_zero(
    tmp_path,
):

    (
        db,
        _,
        _,
        service,
    ) = build_environment(
        tmp_path
    )

    create_pending_order(
        service,
        order_id="order-1",
    )

    result = (
        PendingOrderAuditor(
            db
        )
        .audit_session(
            SESSION
        )
    )

    assert (
        result.records[0]
        .execution_attempt_count
        == 0
    )


def test_missing_decision_lineage_is_not_clean(
    tmp_path,
):

    (
        db,
        _,
        _,
        service,
    ) = build_environment(
        tmp_path
    )

    create_pending_order(
        service,
        order_id="order-1",
    )

    result = (
        PendingOrderAuditor(
            db
        )
        .audit_session(
            SESSION
        )
    )

    assert (
        result.records[0]
        .clean_for_execution
        is False
    )


def test_no_pending_orders_returns_empty(
    tmp_path,
):

    (
        db,
        _,
        _,
        _,
    ) = build_environment(
        tmp_path
    )

    result = (
        PendingOrderAuditor(
            db
        )
        .audit_session(
            SESSION
        )
    )

    assert (
        result.total_orders
        == 0
    )

    assert (
        result.records
        == ()
    )