from __future__ import annotations

from datetime import (
    date,
    datetime,
    timezone,
)
from decimal import Decimal

import pandas as pd
import pytest

from database.storage import (
    MarketDataStorage,
)
from database.trading_storage import (
    TradingStorage,
    TradingStorageError,
)
from services.data_quality import (
    DataQualityReport,
)
from services.market_data import (
    MarketDataResult,
)
from trading.orders import (
    Fill,
    Order,
    OrderSide,
    OrderStatus,
)


def create_market_run(
    db,
    session_date: date,
    price: float,
) -> str:
    """
    Create a real persisted ingestion run so
    foreign-key lineage can be tested properly.
    """

    storage = MarketDataStorage(
        db
    )

    storage.initialize()

    index = pd.to_datetime(
        [
            session_date.isoformat(),
        ]
    )

    data = pd.DataFrame(
        {
            "Open": [price],
            "High": [price + 1],
            "Low": [price - 1],
            "Close": [price],
            "Adj Close": [price],
            "Volume": [1_000_000],
        },
        index=index,
    )

    result = MarketDataResult(
        ticker="AAPL",
        data=data,
        provider="test",
        retrieved_at_utc=datetime(
            session_date.year,
            session_date.month,
            session_date.day,
            22,
            0,
            tzinfo=timezone.utc,
        ),
    )

    report = DataQualityReport(
        ticker="AAPL",
        checked_at_utc=datetime(
            session_date.year,
            session_date.month,
            session_date.day,
            22,
            1,
            tzinfo=timezone.utc,
        ),
        latest_data_session=(
            session_date
        ),
        latest_expected_completed_session=(
            session_date
        ),
        issues=(),
    )

    saved = (
        storage.save_market_snapshot(
            result=result,
            quality_report=report,
        )
    )

    return saved.run_id


def make_order() -> Order:

    return Order(
        order_id="lineage-order",
        ticker="AAPL",
        side=OrderSide.BUY,
        quantity=5,
        signal_timestamp_utc=datetime(
            2026,
            9,
            4,
            21,
            0,
            tzinfo=timezone.utc,
        ),
        execution_session=date(
            2026,
            9,
            8,
        ),
    )


def make_fill() -> Fill:

    return Fill(
        order_id="lineage-order",
        ticker="AAPL",
        side=OrderSide.BUY,
        quantity=5,
        reference_price=Decimal(
            "101.00"
        ),
        fill_price=Decimal(
            "101.00"
        ),
        gross_value=Decimal(
            "505.00"
        ),
        fees=Decimal(
            "0.00"
        ),
        slippage_cost=Decimal(
            "0.00"
        ),
        execution_session=date(
            2026,
            9,
            8,
        ),
        status=OrderStatus.FILLED,
        realized_pnl=Decimal(
            "0.00"
        ),
    )


def test_order_records_explicit_decision_lineage(
    tmp_path,
):

    db = (
        tmp_path
        / "test.db"
    )

    decision_run_id = create_market_run(
        db=db,
        session_date=date(
            2026,
            9,
            4,
        ),
        price=100.0,
    )

    trades = TradingStorage(
        db
    )

    trades.initialize()

    trades.save_order(
        order=make_order(),
        decision_run_id=(
            decision_run_id
        ),
    )

    stored = trades.get_order(
        "lineage-order"
    )

    assert stored is not None

    assert (
        stored.decision_run_id
        == decision_run_id
    )

    # New API should not need to populate
    # the ambiguous legacy column.
    assert (
        stored.source_run_id
        is None
    )


def test_fill_records_explicit_execution_lineage(
    tmp_path,
):

    db = (
        tmp_path
        / "test.db"
    )

    decision_run_id = create_market_run(
        db=db,
        session_date=date(
            2026,
            9,
            4,
        ),
        price=100.0,
    )

    execution_run_id = create_market_run(
        db=db,
        session_date=date(
            2026,
            9,
            8,
        ),
        price=101.0,
    )

    trades = TradingStorage(
        db
    )

    trades.initialize()

    trades.save_order(
        order=make_order(),
        decision_run_id=(
            decision_run_id
        ),
    )

    trades.save_fill(
        fill=make_fill(),
        execution_run_id=(
            execution_run_id
        ),
    )

    fills = trades.list_fills()

    assert len(fills) == 1

    assert (
        fills[0].execution_run_id
        == execution_run_id
    )

    stored_order = trades.get_order(
        "lineage-order"
    )

    assert (
        stored_order.decision_run_id
        == decision_run_id
    )

    assert (
        stored_order.decision_run_id
        != fills[0].execution_run_id
    )


def test_invalid_decision_run_is_rejected_atomically(
    tmp_path,
):

    db = (
        tmp_path
        / "test.db"
    )

    # Ensure ingestion_runs exists.
    market_storage = (
        MarketDataStorage(
            db
        )
    )

    market_storage.initialize()

    trades = TradingStorage(
        db
    )

    trades.initialize()

    with pytest.raises(
        TradingStorageError
    ):
        trades.save_order(
            order=make_order(),
            decision_run_id=(
                "does-not-exist"
            ),
        )

    # Failed lineage means failed order too.
    assert (
        trades.count_orders()
        == 0
    )


def test_conflicting_order_lineage_aliases_fail_closed(
    tmp_path,
):

    db = (
        tmp_path
        / "test.db"
    )

    trades = TradingStorage(
        db
    )

    trades.initialize()

    with pytest.raises(
        ValueError
    ):
        trades.save_order(
            order=make_order(),
            source_run_id=(
                "legacy-run"
            ),
            decision_run_id=(
                "different-run"
            ),
        )


def test_conflicting_fill_lineage_aliases_fail_closed(
    tmp_path,
):

    db = (
        tmp_path
        / "test.db"
    )

    trades = TradingStorage(
        db
    )

    trades.initialize()

    with pytest.raises(
        ValueError
    ):
        trades.save_fill(
            fill=make_fill(),
            source_run_id=(
                "legacy-run"
            ),
            execution_run_id=(
                "different-run"
            ),
        )