from __future__ import annotations

import argparse
from dataclasses import dataclass
from decimal import Decimal

from model2_config import MODEL_2_ACCOUNT_ID
from model2_decision_context import (
    build_model2_decision_context,
)
from model2_universe import (
    MODEL2_GROUPS,
    MODEL2_TICKERS,
)
from services.data_quality import (
    MarketDataQualityValidator,
)
from services.market_data import (
    YahooFinanceProvider,
)
from signals.signal_engine import (
    SignalAction,
)


@dataclass(frozen=True)
class RankedCandidate:
    rank: int
    ticker: str
    group: str
    momentum: Decimal
    close: Decimal
    moving_average: Decimal
    bars_used: int


@dataclass(frozen=True)
class ExitCandidate:
    ticker: str
    group: str
    momentum: Decimal
    reason: str


@dataclass(frozen=True)
class CandidateScanResult:
    candidates: tuple[RankedCandidate, ...]
    exits: tuple[ExitCandidate, ...]
    failures: tuple[tuple[str, str], ...]
    scanned: int


def scan_model2_candidates(
    *,
    top_n: int = 10,
) -> CandidateScanResult:
    """
    Evaluate the Model 2 universe without creating,
    modifying, rejecting, or executing any orders.

    New BUY candidates are ranked by the same
    20-session momentum already produced by the
    existing SignalEngine.

    Existing-position EXIT signals are kept separate
    and are never forced to compete with BUY rankings.
    """

    if top_n < 1:
        raise ValueError(
            "top_n must be at least 1."
        )

    context = build_model2_decision_context()

    portfolio = context.portfolio_rebuilder.rebuild(
        account_id=MODEL_2_ACCOUNT_ID
    )

    provider = YahooFinanceProvider()

    validator = MarketDataQualityValidator(
        calendar_name="NYSE"
    )

    signal_engine = (
        context.decision_pipeline.signal_engine
    )

    buy_signals = []
    exit_signals = []
    failures = []

    for ticker in MODEL2_TICKERS:
        try:
            market_result = (
                provider.get_daily_history(
                    ticker=ticker,
                    period="1y",
                )
            )

            quality_report = validator.validate(
                market_result
            )

            position = portfolio.positions.get(
                ticker
            )

            has_position = (
                position is not None
                and position.quantity > 0
            )

            signal = signal_engine.generate(
                market_result=market_result,
                quality_report=quality_report,
                has_position=has_position,
            )

            if signal.action == SignalAction.BUY:

                if (
                    signal.momentum is None
                    or signal.close is None
                    or signal.moving_average is None
                ):
                    raise RuntimeError(
                        "BUY signal is missing "
                        "ranking inputs."
                    )

                buy_signals.append(
                    (
                        ticker,
                        signal.momentum,
                        signal.close,
                        signal.moving_average,
                        signal.bars_used,
                    )
                )

            elif signal.action == SignalAction.EXIT:

                if signal.momentum is None:
                    raise RuntimeError(
                        "EXIT signal is missing "
                        "momentum."
                    )

                exit_signals.append(
                    ExitCandidate(
                        ticker=ticker,
                        group=MODEL2_GROUPS[ticker],
                        momentum=signal.momentum,
                        reason=signal.reason.value,
                    )
                )

        except Exception as exc:
            failures.append(
                (
                    ticker,
                    f"{type(exc).__name__}: {exc}",
                )
            )

    # Higher positive 20-session momentum ranks first.
    buy_signals.sort(
        key=lambda item: (
            item[1],
            item[0],
        ),
        reverse=True,
    )

    ranked = []

    for index, (
        ticker,
        momentum,
        close,
        moving_average,
        bars_used,
    ) in enumerate(
        buy_signals[:top_n],
        start=1,
    ):
        ranked.append(
            RankedCandidate(
                rank=index,
                ticker=ticker,
                group=MODEL2_GROUPS[ticker],
                momentum=momentum,
                close=close,
                moving_average=moving_average,
                bars_used=bars_used,
            )
        )

    return CandidateScanResult(
        candidates=tuple(ranked),
        exits=tuple(exit_signals),
        failures=tuple(failures),
        scanned=len(MODEL2_TICKERS),
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only Model 2 strongest-candidate "
            "scanner."
        )
    )

    parser.add_argument(
        "--top",
        type=int,
        default=10,
        help=(
            "Number of strongest BUY candidates "
            "to display. Default: 10."
        ),
    )

    args = parser.parse_args()

    result = scan_model2_candidates(
        top_n=args.top
    )

    print()
    print("MODEL 2 CANDIDATE RANKING")
    print("=========================")
    print("READ ONLY")
    print()
    print(
        f"Universe scanned: {result.scanned}"
    )
    print(
        "Ranking metric: 20-session momentum"
    )
    print()

    print("STRONGEST NEW BUY CANDIDATES")
    print("----------------------------")

    if not result.candidates:
        print("No BUY candidates currently qualify.")

    else:
        print(
            f"{'Rank':<6}"
            f"{'Ticker':<8}"
            f"{'Momentum':<12}"
            f"{'Close':<12}"
            f"Group"
        )

        for candidate in result.candidates:
            momentum_pct = (
                candidate.momentum
                * Decimal("100")
            )

            print(
                f"{candidate.rank:<6}"
                f"{candidate.ticker:<8}"
                f"{momentum_pct:>8.2f}%   "
                f"${candidate.close:>9.2f}  "
                f"{candidate.group}"
            )

    print()
    print("EXIT SIGNALS")
    print("------------")

    if not result.exits:
        print(
            "No current holdings have an EXIT signal."
        )

    else:
        for item in result.exits:
            momentum_pct = (
                item.momentum
                * Decimal("100")
            )

            print(
                f"{item.ticker}: "
                f"{momentum_pct:.2f}% "
                f"| {item.reason}"
            )

    print()
    print("SCAN FAILURES")
    print("-------------")

    if not result.failures:
        print("None")

    else:
        for ticker, error in result.failures:
            print(
                f"{ticker}: {error}"
            )

    print()
    print(
        "No orders or database records were changed."
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())