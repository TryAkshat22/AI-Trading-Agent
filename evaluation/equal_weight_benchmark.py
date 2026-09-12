from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Callable, Sequence

import pandas as pd

from database.equity_storage import (
    EquitySnapshot,
)
from services.market_data import (
    MarketDataResult,
)


class EqualWeightBenchmarkError(
    Exception
):
    pass


@dataclass(frozen=True)
class EqualWeightBenchmarkPoint:

    session: date

    model_equity: Decimal
    benchmark_value: Decimal

    model_return_pct: Decimal
    benchmark_return_pct: Decimal

    excess_return_pct: Decimal


@dataclass(frozen=True)
class EqualWeightBenchmarkComparison:

    symbols: tuple[str, ...]

    starting_equity: Decimal
    ending_equity: Decimal

    starting_benchmark_value: Decimal
    ending_benchmark_value: Decimal

    model_total_return_pct: Decimal
    benchmark_total_return_pct: Decimal

    excess_return_pct: Decimal

    points: tuple[
        EqualWeightBenchmarkPoint,
        ...,
    ]


class EqualWeightBenchmarkService:
    """
    Passive equal-weight buy-and-hold benchmark.

    Capital is divided equally among all symbols
    on the first valuation session.

    Holdings are then left untouched.

    No rebalancing occurs.
    """

    def __init__(
        self,
        market_data_fetcher: Callable[
            [str],
            MarketDataResult,
        ],
        symbols: Sequence[str],
    ) -> None:

        normalized = tuple(
            dict.fromkeys(
                symbol.strip().upper()
                for symbol in symbols
                if symbol.strip()
            )
        )

        if not normalized:

            raise ValueError(
                "Equal-weight benchmark "
                "requires at least one symbol."
            )

        self.symbols = normalized

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

    def _load_price_series(
        self,
        symbol: str,
        sessions: Sequence[
            date
        ],
    ) -> dict[
        date,
        Decimal,
    ]:

        result = (
            self.market_data_fetcher(
                symbol
            )
        )

        data = result.data

        if (
            data is None
            or data.empty
        ):

            raise EqualWeightBenchmarkError(
                f"No market data returned "
                f"for {symbol}."
            )

        if (
            "Adj Close"
            not in data.columns
        ):

            raise EqualWeightBenchmarkError(
                f"{symbol} requires "
                "Adj Close."
            )

        prices: dict[
            date,
            Decimal,
        ] = {}

        for timestamp, raw_price in zip(
            pd.DatetimeIndex(
                data.index
            ),
            data[
                "Adj Close"
            ],
        ):

            session = (
                pd.Timestamp(
                    timestamp
                ).date()
            )

            price = (
                self._decimal(
                    raw_price
                )
            )

            if price <= 0:

                raise EqualWeightBenchmarkError(
                    f"Invalid price for "
                    f"{symbol} on "
                    f"{session}."
                )

            prices[
                session
            ] = price

        for session in sessions:

            if session not in prices:

                raise EqualWeightBenchmarkError(
                    f"Missing {symbol} "
                    f"benchmark data for "
                    f"{session}."
                )

        return prices

    def compare(
        self,
        equity_history: Sequence[
            EquitySnapshot
        ],
    ) -> EqualWeightBenchmarkComparison:

        snapshots = tuple(
            sorted(
                equity_history,
                key=lambda snapshot:
                snapshot.valuation_session,
            )
        )

        if not snapshots:

            raise EqualWeightBenchmarkError(
                "Equity history is empty."
            )

        for snapshot in snapshots:

            if (
                snapshot.total_equity
                <= 0
            ):

                raise EqualWeightBenchmarkError(
                    "Equity must be positive."
                )

        sessions = tuple(
            snapshot.valuation_session
            for snapshot in snapshots
        )

        starting_equity = (
            snapshots[
                0
            ].total_equity
        )

        price_series: dict[
            str,
            dict[
                date,
                Decimal,
            ],
        ] = {}

        for symbol in self.symbols:

            price_series[
                symbol
            ] = (
                self._load_price_series(
                    symbol,
                    sessions,
                )
            )

        first_session = (
            sessions[
                0
            ]
        )

        allocation_per_symbol = (
            starting_equity
            / Decimal(
                len(
                    self.symbols
                )
            )
        )

        shares: dict[
            str,
            Decimal,
        ] = {}

        for symbol in self.symbols:

            starting_price = (
                price_series[
                    symbol
                ][
                    first_session
                ]
            )

            shares[
                symbol
            ] = (
                allocation_per_symbol
                / starting_price
            )

        points: list[
            EqualWeightBenchmarkPoint
        ] = []

        for snapshot in snapshots:

            session = (
                snapshot
                .valuation_session
            )

            benchmark_value = sum(
                (
                    shares[
                        symbol
                    ]
                    * price_series[
                        symbol
                    ][
                        session
                    ]
                )
                for symbol
                in self.symbols
            )

            model_return_pct = (
                (
                    snapshot.total_equity
                    / starting_equity
                )
                - Decimal(
                    "1"
                )
            ) * Decimal(
                "100"
            )

            benchmark_return_pct = (
                (
                    benchmark_value
                    / starting_equity
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

            points.append(
                EqualWeightBenchmarkPoint(
                    session=session,
                    model_equity=(
                        snapshot
                        .total_equity
                    ),
                    benchmark_value=(
                        benchmark_value
                    ),
                    model_return_pct=(
                        model_return_pct
                    ),
                    benchmark_return_pct=(
                        benchmark_return_pct
                    ),
                    excess_return_pct=(
                        excess_return_pct
                    ),
                )
            )

        ending_equity = (
            snapshots[
                -1
            ].total_equity
        )

        ending_benchmark_value = (
            points[
                -1
            ].benchmark_value
        )

        model_total_return_pct = (
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

        benchmark_total_return_pct = (
            (
                ending_benchmark_value
                / starting_equity
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

        return (
            EqualWeightBenchmarkComparison(
                symbols=(
                    self.symbols
                ),
                starting_equity=(
                    starting_equity
                ),
                ending_equity=(
                    ending_equity
                ),
                starting_benchmark_value=(
                    starting_equity
                ),
                ending_benchmark_value=(
                    ending_benchmark_value
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
                    points
                ),
            )
        )


def print_equal_weight_benchmark(
    comparison:
    EqualWeightBenchmarkComparison,
) -> None:

    print()
    print(
        "Model vs Equal-Weight Buy-and-Hold"
    )

    print(
        "=================================="
    )

    print(
        f"Universe size:     "
        f"{len(comparison.symbols)}"
    )

    print(
        f"Model return:      "
        f"{comparison.model_total_return_pct:.2f}%"
    )

    print(
        f"Benchmark return:  "
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
        "Benchmark %  "
        "Excess %"
    )

    for point in comparison.points:

        print(
            f"{point.session}  "
            f"{point.model_return_pct:>8.2f}%  "
            f"{point.benchmark_return_pct:>10.2f}%  "
            f"{point.excess_return_pct:>8.2f}%"
        )