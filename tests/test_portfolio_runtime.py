from decimal import Decimal

import runtime


def test_live_runtime_empty_portfolio_report(
    tmp_path,
):

    db = (
        tmp_path
        / "portfolio-runtime.db"
    )

    live = (
        runtime.build_live_runtime(
            db
        )
    )

    report = (
        live.get_portfolio_report()
    )

    assert (
        report.starting_cash
        == Decimal(
            "10000.00"
        )
    )

    assert (
        report.cash
        == Decimal(
            "10000.00"
        )
    )

    assert (
        report.market_value
        == Decimal(
            "0.00"
        )
    )

    assert (
        report.total_equity
        == Decimal(
            "10000.00"
        )
    )

    assert (
        report.total_pnl
        == Decimal(
            "0.00"
        )
    )

    assert (
        report.total_return_pct
        == Decimal(
            "0"
        )
    )

    assert (
        report.exposure_pct
        == Decimal(
            "0"
        )
    )

    assert (
        report.open_positions
        == 0
    )

    assert (
        report.trade_count
        == 0
    )