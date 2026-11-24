from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Sequence

from model2_universe import MODEL2_GROUPS

from signals.signal_engine import SignalResult

from trading.decision_pipeline import (
    DecisionStatus,
    TradeDecision,
)


class Model2TradeSelectorError(RuntimeError):
    """Model 2 trade-selection configuration is invalid."""


@dataclass(frozen=True)
class Model2TradeSelection:
    exit_tickers: tuple[str, ...]
    selected_buy_tickers: tuple[str, ...]
    skipped_buy_tickers: tuple[str, ...]

    @property
    def selected_tickers(self) -> tuple[str, ...]:
        return (
            self.exit_tickers
            + self.selected_buy_tickers
        )


def _ranking_momentum(
    decision: TradeDecision,
) -> Decimal:
    """
    Return momentum used for BUY ranking.

    Real production SignalResult objects must contain
    momentum for an approved BUY.

    Some existing integration tests use lightweight
    signal fakes that predate candidate ranking. Those
    receive a neutral zero value so the old test contract
    remains valid.
    """

    signal = decision.signal

    momentum = getattr(
        signal,
        "momentum",
        None,
    )

    if momentum is not None:
        return Decimal(
            str(momentum)
        )

    if isinstance(
        signal,
        SignalResult,
    ):
        raise Model2TradeSelectorError(
            f"Approved BUY {decision.ticker} "
            "has no momentum."
        )

    # Compatibility only for legacy/fake test signals.
    return Decimal("0")


def select_model2_trades(
    decisions: Sequence[TradeDecision],
    *,
    max_new_buys: int = 5,
    max_buys_per_group: int = 2,
) -> Model2TradeSelection:

    if max_new_buys < 1:
        raise Model2TradeSelectorError(
            "max_new_buys must be at least 1."
        )

    if max_buys_per_group < 1:
        raise Model2TradeSelectorError(
            "max_buys_per_group must be at least 1."
        )

    exits = []
    buys = []

    seen_tickers = set()

    for decision in decisions:

        ticker = (
            decision.ticker
            .strip()
            .upper()
        )

        if not ticker:
            raise Model2TradeSelectorError(
                "Decision contains an empty ticker."
            )

        if ticker in seen_tickers:
            raise Model2TradeSelectorError(
                f"Duplicate decision ticker: {ticker}."
            )

        seen_tickers.add(ticker)

        if (
            decision.status
            == DecisionStatus.EXIT_APPROVED
        ):
            exits.append(decision)
            continue

        if (
            decision.status
            != DecisionStatus.BUY_APPROVED
        ):
            continue

        if ticker not in MODEL2_GROUPS:
            raise Model2TradeSelectorError(
                f"No Model 2 group configured for "
                f"{ticker}."
            )

        buys.append(
            (
                decision,
                _ranking_momentum(
                    decision
                ),
            )
        )

    ranked_buys = sorted(
        buys,
        key=lambda item: (
            -item[1],
            item[0].ticker,
        ),
    )

    group_counts = {}

    selected_buys = []
    skipped_buys = []

    for decision, momentum in ranked_buys:

        ticker = (
            decision.ticker
            .strip()
            .upper()
        )

        group = MODEL2_GROUPS[
            ticker
        ]

        if (
            len(selected_buys)
            >= max_new_buys
        ):
            skipped_buys.append(
                ticker
            )
            continue

        group_count = (
            group_counts.get(
                group,
                0,
            )
        )

        if (
            group_count
            >= max_buys_per_group
        ):
            skipped_buys.append(
                ticker
            )
            continue

        selected_buys.append(
            ticker
        )

        group_counts[group] = (
            group_count + 1
        )

    return Model2TradeSelection(
        exit_tickers=tuple(
            decision.ticker
            .strip()
            .upper()
            for decision in exits
        ),
        selected_buy_tickers=tuple(
            selected_buys
        ),
        skipped_buy_tickers=tuple(
            skipped_buys
        ),
    )