from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Sequence

from database.equity_storage import (
    EquitySnapshot,
)


class CashBenchmarkError(Exception):
    pass


@dataclass(frozen=True)
class CashBenchmarkPoint:
    session: date

    model_equity: Decimal
    cash_value: Decimal

    model_return_pct: Decimal
    cash_return_pct: Decimal

    excess_return_pct: Decimal


@dataclass(frozen=True)
class CashBenchmarkComparison:
    starting_equity: Decimal
    ending_equity: Decimal

    cash_value: Decimal

    model_total_return_pct: Decimal
    cash_total_return_pct: Decimal
    excess_return_pct: Decimal

    points: tuple[
        CashBenchmarkPoint,
        ...,
    ]


class CashBenchmarkService:
    """
    Zero-yield cash benchmark.

    The benchmark assumes the starting portfolio
    equity remains entirely in cash and earns 0%.

    This intentionally differs from a Treasury-bill
    or interest-bearing cash benchmark.
    """

    def compare(
        self,
        equity_history: Sequence[
            EquitySnapshot
        ],
    ) -> CashBenchmarkComparison:

        snapshots = tuple(
            sorted(
                equity_history,
                key=lambda snapshot:
                snapshot.valuation_session,
            )
        )

        if not snapshots:

            raise CashBenchmarkError(
                "Equity history is empty."
            )

        starting_equity = (
            snapshots[
                0
            ].total_equity
        )

        if starting_equity <= 0:

            raise CashBenchmarkError(
                "Starting equity must be positive."
            )

        for snapshot in snapshots:

            if (
                snapshot.total_equity
                <= 0
            ):

                raise CashBenchmarkError(
                    "Equity must be positive."
                )

        cash_value = (
            starting_equity
        )

        cash_return_pct = Decimal(
            "0"
        )

        points: list[
            CashBenchmarkPoint
        ] = []

        for snapshot in snapshots:

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

            excess_return_pct = (
                model_return_pct
                - cash_return_pct
            )

            points.append(
                CashBenchmarkPoint(
                    session=(
                        snapshot
                        .valuation_session
                    ),
                    model_equity=(
                        snapshot
                        .total_equity
                    ),
                    cash_value=(
                        cash_value
                    ),
                    model_return_pct=(
                        model_return_pct
                    ),
                    cash_return_pct=(
                        cash_return_pct
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

        excess_return_pct = (
            model_total_return_pct
            - cash_return_pct
        )

        return CashBenchmarkComparison(
            starting_equity=(
                starting_equity
            ),
            ending_equity=(
                ending_equity
            ),
            cash_value=(
                cash_value
            ),
            model_total_return_pct=(
                model_total_return_pct
            ),
            cash_total_return_pct=(
                cash_return_pct
            ),
            excess_return_pct=(
                excess_return_pct
            ),
            points=tuple(
                points
            ),
        )


def print_cash_benchmark(
    comparison: CashBenchmarkComparison,
) -> None:

    print()
    print(
        "Model vs Cash"
    )

    print(
        "============="
    )

    print(
        f"Model return:      "
        f"{comparison.model_total_return_pct:.2f}%"
    )

    print(
        f"Cash return:       "
        f"{comparison.cash_total_return_pct:.2f}%"
    )

    print(
        f"Excess return:     "
        f"{comparison.excess_return_pct:.2f}%"
    )

    print()

    print(
        "Session      "
        "Model %      "
        "Cash %       "
        "Excess %"
    )

    for point in comparison.points:

        print(
            f"{point.session}  "
            f"{point.model_return_pct:>8.2f}%  "
            f"{point.cash_return_pct:>8.2f}%  "
            f"{point.excess_return_pct:>8.2f}%"
        )