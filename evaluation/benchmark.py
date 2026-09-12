from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Callable, Sequence

import pandas as pd

from database.equity_storage import EquitySnapshot
from services.market_data import (
    MarketDataResult,
)


class BenchmarkError(Exception):
    pass


class BenchmarkDataError(
    BenchmarkError
):
    pass


@dataclass(frozen=True)
class BenchmarkPoint:
    session: date
    price: Decimal


@dataclass(frozen=True)
class BenchmarkComparisonPoint:
    session: date

    model_equity: Decimal
    model_return_pct: Decimal

    benchmark_price: Decimal
    benchmark_return_pct: Decimal

    excess_return_pct: Decimal


@dataclass(frozen=True)
class BenchmarkComparison:
    symbol: str

    starting_model_equity: Decimal
    starting_benchmark_price: Decimal

    ending_model_equity: Decimal
    ending_benchmark_price: Decimal

    model_total_return_pct: Decimal
    benchmark_total_return_pct: Decimal
    excess_return_pct: Decimal

    points: tuple[
        BenchmarkComparisonPoint,
        ...,
    ]


class BenchmarkService:
    """
    Aligns a benchmark price series to persisted
    portfolio-equity valuation sessions.

    Benchmark performance is normalized from the
    first shared session.
    """

    def __init__(
        self,
        market_data_fetcher: Callable[
            [str],
            MarketDataResult,
        ],
        symbol: str = "SPY",
    ) -> None:

        normalized = (
            symbol.strip().upper()
        )

        if not normalized:

            raise ValueError(
                "Benchmark symbol cannot be blank."
            )

        self.symbol = normalized
        self.market_data_fetcher = (
            market_data_fetcher
        )

    @staticmethod
    def _decimal(
        value,
    ) -> Decimal:

        return Decimal(
            str(
                value
            )
        )

    def _load_points(
        self,
        sessions: Sequence[date],
    ) -> tuple[
        BenchmarkPoint,
        ...,
    ]:

        if not sessions:
            return ()

        result = (
            self.market_data_fetcher(
                self.symbol
            )
        )

        data = result.data

        if data is None or data.empty:

            raise BenchmarkDataError(
                f"No benchmark data returned "
                f"for {self.symbol}."
            )

        if (
            "Adj Close"
            not in data.columns
        ):

            raise BenchmarkDataError(
                f"{self.symbol} benchmark data "
                "requires Adj Close."
            )

        frame = data.copy()

        index = pd.DatetimeIndex(
            frame.index
        )

        session_map: dict[
            date,
            Decimal,
        ] = {}

        for timestamp, value in zip(
            index,
            frame[
                "Adj Close"
            ],
            strict=True,
        ):

            session = (
                pd.Timestamp(
                    timestamp
                ).date()
            )

            price = (
                self._decimal(
                    value
                )
            )

            if price <= 0:

                raise BenchmarkDataError(
                    f"Invalid benchmark price "
                    f"for {self.symbol} on "
                    f"{session}."
                )

            session_map[
                session
            ] = price

        points: list[
            BenchmarkPoint
        ] = []

        for session in sessions:

            price = session_map.get(
                session
            )

            if price is None:

                raise BenchmarkDataError(
                    f"Missing {self.symbol} "
                    f"benchmark data for "
                    f"{session}."
                )

            points.append(
                BenchmarkPoint(
                    session=session,
                    price=price,
                )
            )

        return tuple(
            points
        )

    def compare(
        self,
        equity_history: Sequence[
            EquitySnapshot
        ],
    ) -> BenchmarkComparison:

        snapshots = tuple(
            sorted(
                equity_history,
                key=lambda snapshot:
                snapshot.valuation_session,
            )
        )

        if not snapshots:

            raise BenchmarkDataError(
                "Equity history is empty."
            )

        sessions = tuple(
            snapshot.valuation_session
            for snapshot in snapshots
        )

        benchmark_points = (
            self._load_points(
                sessions
            )
        )

        starting_model_equity = (
            snapshots[
                0
            ].total_equity
        )

        starting_benchmark_price = (
            benchmark_points[
                0
            ].price
        )

        if starting_model_equity <= 0:

            raise BenchmarkDataError(
                "Starting model equity "
                "must be positive."
            )

        if starting_benchmark_price <= 0:

            raise BenchmarkDataError(
                "Starting benchmark price "
                "must be positive."
            )

        comparison_points: list[
            BenchmarkComparisonPoint
        ] = []

        for snapshot, benchmark in zip(
            snapshots,
            benchmark_points,
            strict=True,
        ):

            model_return_pct = (
                (
                    snapshot.total_equity
                    / starting_model_equity
                )
                - Decimal(
                    "1"
                )
            ) * Decimal(
                "100"
            )

            benchmark_return_pct = (
                (
                    benchmark.price
                    / starting_benchmark_price
                )
                - Decimal(
                    "1"
                )
            ) * Decimal(
                "100"
            )

            excess_return_pct = (
                model_return_pct
                - benchmark_return_pct
            )

            comparison_points.append(
                BenchmarkComparisonPoint(
                    session=(
                        snapshot
                        .valuation_session
                    ),
                    model_equity=(
                        snapshot
                        .total_equity
                    ),
                    model_return_pct=(
                        model_return_pct
                    ),
                    benchmark_price=(
                        benchmark.price
                    ),
                    benchmark_return_pct=(
                        benchmark_return_pct
                    ),
                    excess_return_pct=(
                        excess_return_pct
                    ),
                )
            )

        ending_model_equity = (
            snapshots[
                -1
            ].total_equity
        )

        ending_benchmark_price = (
            benchmark_points[
                -1
            ].price
        )

        model_total_return_pct = (
            (
                ending_model_equity
                / starting_model_equity
            )
            - Decimal(
                "1"
            )
        ) * Decimal(
            "100"
        )

        benchmark_total_return_pct = (
            (
                ending_benchmark_price
                / starting_benchmark_price
            )
            - Decimal(
                "1"
            )
        ) * Decimal(
            "100"
        )

        excess_return_pct = (
            model_total_return_pct
            - benchmark_total_return_pct
        )

        return BenchmarkComparison(
            symbol=self.symbol,
            starting_model_equity=(
                starting_model_equity
            ),
            starting_benchmark_price=(
                starting_benchmark_price
            ),
            ending_model_equity=(
                ending_model_equity
            ),
            ending_benchmark_price=(
                ending_benchmark_price
            ),
            model_total_return_pct=(
                model_total_return_pct
            ),
            benchmark_total_return_pct=(
                benchmark_total_return_pct
            ),
            excess_return_pct=(
                excess_return_pct
            ),
            points=tuple(
                comparison_points
            ),
        )


def print_benchmark_comparison(
    comparison: BenchmarkComparison,
) -> None:

    print()
    print(
        f"Model vs {comparison.symbol}"
    )

    print(
        "=" * (
            len(
                comparison.symbol
            )
            + 9
        )
    )

    print(
        f"Model return:      "
        f"{comparison.model_total_return_pct:.2f}%"
    )

    print(
        f"{comparison.symbol} return:       "
        f"{comparison.benchmark_total_return_pct:.2f}%"
    )

    print(
        f"Excess return:     "
        f"{comparison.excess_return_pct:.2f}%"
    )

    print()

    print(
        "Session      "
        "Model %      "
        f"{comparison.symbol} %      "
        "Excess %"
    )

    for point in comparison.points:

        print(
            f"{point.session}  "
            f"{point.model_return_pct:>8.2f}%  "
            f"{point.benchmark_return_pct:>8.2f}%  "
            f"{point.excess_return_pct:>8.2f}%"
        )