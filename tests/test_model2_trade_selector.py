from decimal import Decimal

from model2_trade_selector import (
    select_model2_trades,
)

from signals.signal_engine import (
    SignalAction,
    SignalReason,
    SignalResult,
)

from trading.decision_pipeline import (
    DecisionStatus,
    TradeDecision,
)

from trading.orders import OrderSide


def make_buy(
    ticker: str,
    momentum: str,
) -> TradeDecision:

    signal = SignalResult(
        ticker=ticker,
        action=SignalAction.BUY,
        reason=SignalReason.BULLISH_TREND,
        source_session=None,
        close=Decimal("100"),
        moving_average=Decimal("90"),
        momentum=Decimal(momentum),
        bars_used=100,
    )

    return TradeDecision(
        ticker=ticker,
        status=DecisionStatus.BUY_APPROVED,
        signal=signal,
        side=OrderSide.BUY,
        quantity=1,
        position_size=None,
        risk_assessment=None,
    )


def make_exit(
    ticker: str,
) -> TradeDecision:

    signal = SignalResult(
        ticker=ticker,
        action=SignalAction.EXIT,
        reason=SignalReason.EXIT_TREND_FAILED,
        source_session=None,
        close=Decimal("100"),
        moving_average=Decimal("110"),
        momentum=Decimal("-0.01"),
        bars_used=100,
    )

    return TradeDecision(
        ticker=ticker,
        status=DecisionStatus.EXIT_APPROVED,
        signal=signal,
        side=OrderSide.SELL,
        quantity=1,
        position_size=None,
        risk_assessment=None,
    )


def test_selects_only_top_five_buys():

    decisions = [
        make_buy("LLY", "0.24"),
        make_buy("COP", "0.21"),
        make_buy("WMT", "0.18"),
        make_buy("HD", "0.16"),
        make_buy("XOM", "0.14"),
        make_buy("CVX", "0.13"),
        make_buy("NUE", "0.12"),
    ]

    result = select_model2_trades(
        decisions
    )

    assert len(
        result.selected_buy_tickers
    ) == 5


def test_maximum_two_buys_per_group():

    decisions = [
        make_buy("XOM", "0.30"),
        make_buy("CVX", "0.29"),
        make_buy("COP", "0.28"),
        make_buy("LLY", "0.27"),
        make_buy("WMT", "0.26"),
        make_buy("NUE", "0.25"),
    ]

    result = select_model2_trades(
        decisions
    )

    assert "XOM" in result.selected_buy_tickers
    assert "CVX" in result.selected_buy_tickers

    assert "COP" not in (
        result.selected_buy_tickers
    )

    assert "COP" in (
        result.skipped_buy_tickers
    )


def test_exit_bypasses_buy_limit():

    decisions = [
        make_exit("AAPL"),
        make_exit("JNJ"),

        make_buy("LLY", "0.24"),
        make_buy("COP", "0.21"),
        make_buy("WMT", "0.18"),
        make_buy("HD", "0.16"),
        make_buy("XOM", "0.14"),
        make_buy("NUE", "0.13"),
    ]

    result = select_model2_trades(
        decisions
    )

    assert result.exit_tickers == (
        "AAPL",
        "JNJ",
    )

    assert len(
        result.selected_buy_tickers
    ) == 5

    assert len(
        result.selected_tickers
    ) == 7


def test_higher_momentum_ranks_first():

    decisions = [
        make_buy("WMT", "0.10"),
        make_buy("LLY", "0.25"),
        make_buy("NUE", "0.15"),
    ]

    result = select_model2_trades(
        decisions,
        max_new_buys=3,
    )

    assert result.selected_buy_tickers == (
        "LLY",
        "NUE",
        "WMT",
    )