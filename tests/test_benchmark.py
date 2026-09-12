from datetime import (
    date,
    datetime,
    timezone,
)
from decimal import Decimal

import pandas as pd
import pytest

from database.equity_storage import (
    EquitySnapshot,
)
from evaluation.benchmark import (
    BenchmarkDataError,
    BenchmarkService,
)
from services.market_data import (
    MarketDataResult,
)


def snapshot(
    session: date,
    equity: str,
):

    equity_value = Decimal(
        equity
    )

    return EquitySnapshot(
        snapshot_id=(
            f"snapshot-{session}"
        ),
        account_id="model1-paper",
        model_version="model-1",
        valuation_session=session,
        starting_cash=Decimal(
            "10000"
        ),
        cash=Decimal(
            "0"
        ),
        market_value=(
            equity_value
        ),
        total_equity=(
            equity_value
        ),
        realized_pnl=Decimal(
            "0"
        ),
        unrealized_pnl=Decimal(
            "0"
        ),
        total_pnl=(
            equity_value
            - Decimal(
                "10000"
            )
        ),
        total_return_pct=(
            (
                equity_value
                / Decimal(
                    "10000"
                )
                - Decimal(
                    "1"
                )
            )
            * Decimal(
                "100"
            )
        ),
        exposure_pct=Decimal(
            "100"
        ),
        open_positions=1,
        recorded_at_utc=datetime(
            2026,
            9,
            14,
            20,
            0,
            tzinfo=timezone.utc,
        ),
    )


def market_result(
    prices: dict[
        str,
        float,
    ],
):

    index = pd.to_datetime(
        list(
            prices.keys()
        )
    )

    data = pd.DataFrame(
        {
            "Adj Close": list(
                prices.values()
            ),
        },
        index=index,
    )

    return MarketDataResult(
        ticker="SPY",
        data=data,
        provider="fake",
        retrieved_at_utc=datetime(
            2026,
            9,
            18,
            20,
            0,
            tzinfo=timezone.utc,
        ),
    )


def test_basic_comparison():

    history = [
        snapshot(
            date(
                2026,
                9,
                14,
            ),
            "10000",
        ),
        snapshot(
            date(
                2026,
                9,
                15,
            ),
            "10200",
        ),
    ]

    result = market_result(
        {
            "2026-09-14": 500,
            "2026-09-15": 505,
        }
    )

    service = BenchmarkService(
        market_data_fetcher=(
            lambda symbol:
            result
        )
    )

    comparison = (
        service.compare(
            history
        )
    )

    assert (
        comparison
        .model_total_return_pct
        == Decimal(
            "2.00"
        )
    )

    assert (
        comparison
        .benchmark_total_return_pct
        == Decimal(
            "1.00"
        )
    )

    assert (
        comparison
        .excess_return_pct
        == Decimal(
            "1.00"
        )
    )


def test_first_session_returns_zero():

    history = [
        snapshot(
            date(
                2026,
                9,
                14,
            ),
            "10000",
        ),
        snapshot(
            date(
                2026,
                9,
                15,
            ),
            "10100",
        ),
    ]

    result = market_result(
        {
            "2026-09-14": 500,
            "2026-09-15": 510,
        }
    )

    comparison = (
        BenchmarkService(
            lambda symbol:
            result
        )
        .compare(
            history
        )
    )

    first = (
        comparison.points[
            0
        ]
    )

    assert (
        first.model_return_pct
        == Decimal(
            "0"
        )
    )

    assert (
        first.benchmark_return_pct
        == Decimal(
            "0"
        )
    )

    assert (
        first.excess_return_pct
        == Decimal(
            "0"
        )
    )


def test_history_is_sorted():

    history = [
        snapshot(
            date(
                2026,
                9,
                15,
            ),
            "10100",
        ),
        snapshot(
            date(
                2026,
                9,
                14,
            ),
            "10000",
        ),
    ]

    result = market_result(
        {
            "2026-09-14": 500,
            "2026-09-15": 505,
        }
    )

    comparison = (
        BenchmarkService(
            lambda symbol:
            result
        )
        .compare(
            history
        )
    )

    assert [
        point.session
        for point
        in comparison.points
    ] == [
        date(
            2026,
            9,
            14,
        ),
        date(
            2026,
            9,
            15,
        ),
    ]


def test_missing_benchmark_session_rejected():

    history = [
        snapshot(
            date(
                2026,
                9,
                14,
            ),
            "10000",
        ),
        snapshot(
            date(
                2026,
                9,
                15,
            ),
            "10100",
        ),
    ]

    result = market_result(
        {
            "2026-09-14": 500,
        }
    )

    with pytest.raises(
        BenchmarkDataError
    ):

        BenchmarkService(
            lambda symbol:
            result
        ).compare(
            history
        )


def test_missing_adjusted_close_rejected():

    result = MarketDataResult(
        ticker="SPY",
        data=pd.DataFrame(
            {
                "Close": [
                    500
                ],
            },
            index=pd.to_datetime(
                [
                    "2026-09-14"
                ]
            ),
        ),
        provider="fake",
        retrieved_at_utc=datetime(
            2026,
            9,
            14,
            20,
            0,
            tzinfo=timezone.utc,
        ),
    )

    with pytest.raises(
        BenchmarkDataError
    ):

        BenchmarkService(
            lambda symbol:
            result
        ).compare(
            [
                snapshot(
                    date(
                        2026,
                        9,
                        14,
                    ),
                    "10000",
                )
            ]
        )


def test_nonpositive_benchmark_price_rejected():

    result = market_result(
        {
            "2026-09-14": 0,
        }
    )

    with pytest.raises(
        BenchmarkDataError
    ):

        BenchmarkService(
            lambda symbol:
            result
        ).compare(
            [
                snapshot(
                    date(
                        2026,
                        9,
                        14,
                    ),
                    "10000",
                )
            ]
        )


def test_empty_equity_history_rejected():

    result = market_result(
        {
            "2026-09-14": 500,
        }
    )

    with pytest.raises(
        BenchmarkDataError
    ):

        BenchmarkService(
            lambda symbol:
            result
        ).compare(
            []
        )


def test_custom_symbol_normalized():

    service = BenchmarkService(
        lambda symbol:
        None,
        symbol="qqq",
    )

    assert (
        service.symbol
        == "QQQ"
    )


def test_blank_symbol_rejected():

    with pytest.raises(
        ValueError
    ):

        BenchmarkService(
            lambda symbol:
            None,
            symbol="   ",
        )


def test_fetcher_receives_symbol():

    calls = []

    result = market_result(
        {
            "2026-09-14": 500,
        }
    )

    def fetcher(
        symbol,
    ):

        calls.append(
            symbol
        )

        return result

    BenchmarkService(
        fetcher,
        symbol="SPY",
    ).compare(
        [
            snapshot(
                date(
                    2026,
                    9,
                    14,
                ),
                "10000",
            )
        ]
    )

    assert (
        calls
        == [
            "SPY"
        ]
    )