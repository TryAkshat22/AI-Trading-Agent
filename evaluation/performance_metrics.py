from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from math import sqrt
from statistics import mean, pstdev
from typing import Sequence

from database.equity_storage import (
    EquitySnapshot,
)


class PerformanceMetricError(Exception):
    pass


@dataclass(frozen=True)
class PerformanceMetrics:

    observations: int

    total_return_pct: Decimal
    annualized_volatility_pct: Decimal

    sharpe_ratio: Decimal | None
    sortino_ratio: Decimal | None

    max_drawdown_pct: Decimal

    positive_day_rate_pct: Decimal
    negative_day_rate_pct: Decimal

    best_day_pct: Decimal
    worst_day_pct: Decimal

    average_daily_return_pct: Decimal


def _to_decimal(
    value,
) -> Decimal:

    return Decimal(
        str(
            value
        )
    )


def _daily_returns(
    equity_history: Sequence[
        EquitySnapshot
    ],
) -> tuple[
    Decimal,
    ...,
]:

    snapshots = tuple(
        sorted(
            equity_history,
            key=lambda snapshot:
            snapshot.valuation_session,
        )
    )

    if len(
        snapshots
    ) < 2:

        return ()

    returns: list[
        Decimal
    ] = []

    for previous, current in zip(
        snapshots,
        snapshots[1:],
    ):

        previous_equity = (
            previous.total_equity
        )

        current_equity = (
            current.total_equity
        )

        if previous_equity <= 0:

            raise PerformanceMetricError(
                "Previous equity must be positive."
            )

        daily_return = (
            (
                current_equity
                / previous_equity
            )
            - Decimal(
                "1"
            )
        )

        returns.append(
            daily_return
        )

    return tuple(
        returns
    )


def _maximum_drawdown(
    equity_history: Sequence[
        EquitySnapshot
    ],
) -> Decimal:

    snapshots = tuple(
        sorted(
            equity_history,
            key=lambda snapshot:
            snapshot.valuation_session,
        )
    )

    if not snapshots:
        raise PerformanceMetricError(
            "Equity history is empty."
        )

    peak = (
        snapshots[
            0
        ].total_equity
    )

    if peak <= 0:

        raise PerformanceMetricError(
            "Equity must be positive."
        )

    max_drawdown = Decimal(
        "0"
    )

    for snapshot in snapshots:

        equity = (
            snapshot.total_equity
        )

        if equity <= 0:

            raise PerformanceMetricError(
                "Equity must be positive."
            )

        if equity > peak:

            peak = equity

        drawdown = (
            (
                equity
                / peak
            )
            - Decimal(
                "1"
            )
        )

        if drawdown < max_drawdown:

            max_drawdown = (
                drawdown
            )

    return (
        abs(
            max_drawdown
        )
        * Decimal(
            "100"
        )
    )


class PerformanceMetricService:

    def __init__(
        self,
        trading_days_per_year: int = 252,
        annual_risk_free_rate: Decimal | int | float | str = 0,
    ) -> None:

        if trading_days_per_year <= 0:

            raise ValueError(
                "trading_days_per_year must "
                "be positive."
            )

        self.trading_days_per_year = (
            trading_days_per_year
        )

        self.annual_risk_free_rate = (
            _to_decimal(
                annual_risk_free_rate
            )
        )

    def calculate(
        self,
        equity_history: Sequence[
            EquitySnapshot
        ],
    ) -> PerformanceMetrics:

        snapshots = tuple(
            sorted(
                equity_history,
                key=lambda snapshot:
                snapshot.valuation_session,
            )
        )

        if not snapshots:

            raise PerformanceMetricError(
                "Equity history is empty."
            )

        for snapshot in snapshots:

            if (
                snapshot.total_equity
                <= 0
            ):

                raise PerformanceMetricError(
                    "Equity must be positive."
                )

        starting_equity = (
            snapshots[
                0
            ].total_equity
        )

        ending_equity = (
            snapshots[
                -1
            ].total_equity
        )

        total_return_pct = (
            (
                ending_equity
                / starting_equity
            )
            - Decimal(
                "1"
            )
        ) * Decimal(
            "100"
        )

        returns = (
            _daily_returns(
                snapshots
            )
        )

        max_drawdown_pct = (
            _maximum_drawdown(
                snapshots
            )
        )

        if not returns:

            return PerformanceMetrics(
                observations=(
                    len(
                        snapshots
                    )
                ),
                total_return_pct=(
                    total_return_pct
                ),
                annualized_volatility_pct=(
                    Decimal(
                        "0"
                    )
                ),
                sharpe_ratio=None,
                sortino_ratio=None,
                max_drawdown_pct=(
                    max_drawdown_pct
                ),
                positive_day_rate_pct=(
                    Decimal(
                        "0"
                    )
                ),
                negative_day_rate_pct=(
                    Decimal(
                        "0"
                    )
                ),
                best_day_pct=(
                    Decimal(
                        "0"
                    )
                ),
                worst_day_pct=(
                    Decimal(
                        "0"
                    )
                ),
                average_daily_return_pct=(
                    Decimal(
                        "0"
                    )
                ),
            )

        float_returns = [
            float(
                value
            )
            for value in returns
        ]

        avg_daily_return = (
            mean(
                float_returns
            )
        )

        daily_volatility = (
            pstdev(
                float_returns
            )
        )

        annualized_volatility = (
            daily_volatility
            * sqrt(
                self.trading_days_per_year
            )
        )

        annual_rf = float(
            self.annual_risk_free_rate
        )

        daily_rf = (
            (
                1
                + annual_rf
            )
            ** (
                1
                / self.trading_days_per_year
            )
            - 1
        )

        excess_daily_returns = [
            value
            - daily_rf
            for value in float_returns
        ]

        excess_mean = (
            mean(
                excess_daily_returns
            )
        )

        sharpe_ratio = None

        if daily_volatility > 0:

            sharpe_ratio = (
                excess_mean
                / daily_volatility
                * sqrt(
                    self.trading_days_per_year
                )
            )

        downside_returns = [
            min(
                value
                - daily_rf,
                0.0,
            )
            for value in float_returns
        ]

        downside_deviation = (
            sqrt(
                mean(
                    value * value
                    for value
                    in downside_returns
                )
            )
        )

        sortino_ratio = None

        if downside_deviation > 0:

            sortino_ratio = (
                excess_mean
                / downside_deviation
                * sqrt(
                    self.trading_days_per_year
                )
            )

        positive_days = sum(
            value > 0
            for value in returns
        )

        negative_days = sum(
            value < 0
            for value in returns
        )

        total_return_days = len(
            returns
        )

        positive_day_rate_pct = (
            Decimal(
                positive_days
            )
            / Decimal(
                total_return_days
            )
            * Decimal(
                "100"
            )
        )

        negative_day_rate_pct = (
            Decimal(
                negative_days
            )
            / Decimal(
                total_return_days
            )
            * Decimal(
                "100"
            )
        )

        best_day_pct = (
            max(
                returns
            )
            * Decimal(
                "100"
            )
        )

        worst_day_pct = (
            min(
                returns
            )
            * Decimal(
                "100"
            )
        )

        average_daily_return_pct = (
            _to_decimal(
                avg_daily_return
            )
            * Decimal(
                "100"
            )
        )

        return PerformanceMetrics(
            observations=(
                len(
                    snapshots
                )
            ),
            total_return_pct=(
                total_return_pct
            ),
            annualized_volatility_pct=(
                _to_decimal(
                    annualized_volatility
                )
                * Decimal(
                    "100"
                )
            ),
            sharpe_ratio=(
                None
                if sharpe_ratio is None
                else _to_decimal(
                    sharpe_ratio
                )
            ),
            sortino_ratio=(
                None
                if sortino_ratio is None
                else _to_decimal(
                    sortino_ratio
                )
            ),
            max_drawdown_pct=(
                max_drawdown_pct
            ),
            positive_day_rate_pct=(
                positive_day_rate_pct
            ),
            negative_day_rate_pct=(
                negative_day_rate_pct
            ),
            best_day_pct=(
                best_day_pct
            ),
            worst_day_pct=(
                worst_day_pct
            ),
            average_daily_return_pct=(
                average_daily_return_pct
            ),
        )


def print_performance_metrics(
    metrics: PerformanceMetrics,
) -> None:

    print()
    print(
        "Performance Metrics"
    )

    print(
        "==================="
    )

    print(
        f"Observations:            "
        f"{metrics.observations}"
    )

    print(
        f"Total return:            "
        f"{metrics.total_return_pct:.2f}%"
    )

    print(
        f"Annualized volatility:   "
        f"{metrics.annualized_volatility_pct:.2f}%"
    )

    print(
        f"Maximum drawdown:        "
        f"{metrics.max_drawdown_pct:.2f}%"
    )

    print(
        f"Average daily return:    "
        f"{metrics.average_daily_return_pct:.4f}%"
    )

    print(
        f"Positive-day rate:       "
        f"{metrics.positive_day_rate_pct:.2f}%"
    )

    print(
        f"Negative-day rate:       "
        f"{metrics.negative_day_rate_pct:.2f}%"
    )

    print(
        f"Best day:                "
        f"{metrics.best_day_pct:.2f}%"
    )

    print(
        f"Worst day:               "
        f"{metrics.worst_day_pct:.2f}%"
    )

    if (
        metrics.sharpe_ratio
        is None
    ):

        print(
            "Sharpe ratio:            "
            "N/A"
        )

    else:

        print(
            f"Sharpe ratio:            "
            f"{metrics.sharpe_ratio:.3f}"
        )

    if (
        metrics.sortino_ratio
        is None
    ):

        print(
            "Sortino ratio:           "
            "N/A"
        )

    else:

        print(
            f"Sortino ratio:           "
            f"{metrics.sortino_ratio:.3f}"
        )