from datetime import date
from decimal import Decimal

import runtime


SESSION = date(
    2026,
    9,
    14,
)


def test_empty_runtime_equity_history(
    tmp_path,
):

    db = (
        tmp_path
        / "equity-runtime.db"
    )

    live = (
        runtime.build_live_runtime(
            db
        )
    )

    history = (
        live.get_equity_history()
    )

    assert history == ()


def test_runtime_records_empty_portfolio_snapshot(
    tmp_path,
):

    db = (
        tmp_path
        / "equity-runtime.db"
    )

    live = (
        runtime.build_live_runtime(
            db
        )
    )

    result = (
        live.record_equity_snapshot(
            SESSION
        )
    )

    assert (
        result.snapshot
        .valuation_session
        == SESSION
    )

    assert (
        result.snapshot
        .total_equity
        == Decimal(
            "10000.00"
        )
    )

    assert (
        result.snapshot
        .market_value
        == Decimal(
            "0.00"
        )
    )


def test_runtime_equity_history_after_record(
    tmp_path,
):

    db = (
        tmp_path
        / "equity-runtime.db"
    )

    live = (
        runtime.build_live_runtime(
            db
        )
    )

    live.record_equity_snapshot(
        SESSION
    )

    history = (
        live.get_equity_history()
    )

    assert (
        len(
            history
        )
        == 1
    )

    assert (
        history[0]
        .valuation_session
        == SESSION
    )