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
from evaluation.equal_weight_benchmark import (
    EqualWeightBenchmarkError,
    EqualWeightBenchmarkService,
)
from services.market_data import (
    MarketDataResult,
)


def snapshot(
    session: date,
    equity: str,
):

    value = Decimal(
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
        market_value=value,
        total_equity=value,
        realized_pnl=Decimal(
            "0"
        ),
        unrealized_pnl=Decimal(
            "0"
        ),
        total_pnl=(
            value
            - Decimal(
                "10000"
            )
        ),
        total_return_pct=Decimal(
            "0"
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
    symbol: str,
    prices: dict[
        str,
        float,
    ],
):

    return MarketDataResult(
        ticker=symbol,
        data=pd.DataFrame(
            {
                "Adj Close": list(
                    prices.values()
                ),
            },
            index=pd.to_datetime(
                list(
                    prices.keys()
                )
            ),
        ),
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


def test_empty_history_rejected():

    service = (
        EqualWeightBenchmarkService(
            market_data_fetcher=(
                lambda symbol:
                None
            ),
            symbols=[
                "AAPL",
            ],
        )
    )

    with pytest.raises(
        EqualWeightBenchmarkError
    ):

        service.compare(
            []
        )


def test_empty_universe_rejected():

    with pytest.raises(
        ValueError
    ):

        EqualWeightBenchmarkService(
            market_data_fetcher=(
                lambda symbol:
                None
            ),
            symbols=[],
        )


def test_symbols_are_normalized():

    service = (
        EqualWeightBenchmarkService(
            market_data_fetcher=(
                lambda symbol:
                None
            ),
            symbols=[
                "aapl",
                " msft ",
                "AAPL",
            ],
        )
    )

    assert (
        service.symbols
        == (
            "AAPL",
            "MSFT",
        )
    )


def test_single_session_starts_at_zero():

    data = {
        "AAPL": market_result(
            "AAPL",
            {
                "2026-09-14": 100,
            },
        ),
        "MSFT": market_result(
            "MSFT",
            {
                "2026-09-14": 200,
            },
        ),
    }

    service = (
        EqualWeightBenchmarkService(
            market_data_fetcher=(
                lambda symbol:
                data[
                    symbol
                ]
            ),
            symbols=[
                "AAPL",
                "MSFT",
            ],
        )
    )

    result = service.compare(
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
        result.benchmark_total_return_pct
        == Decimal(
            "0"
        )
    )

    assert (
        result.starting_benchmark_value
        == Decimal(
            "10000"
        )
    )


def test_equal_weight_buy_and_hold_return():

    data = {
        "AAPL": market_result(
            "AAPL",
            {
                "2026-09-14": 100,
                "2026-09-15": 110,
            },
        ),
        "MSFT": market_result(
            "MSFT",
            {
                "2026-09-14": 200,
                "2026-09-15": 200,
            },
        ),
    }

    result = (
        EqualWeightBenchmarkService(
            market_data_fetcher=(
                lambda symbol:
                data[
                    symbol
                ]
            ),
            symbols=[
                "AAPL",
                "MSFT",
            ],
        )
        .compare(
            [
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
                    "10500",
                ),
            ]
        )
    )

    assert (
        result.benchmark_total_return_pct
        == Decimal(
            "5.00"
        )
    )


def test_model_excess_return():

    data = {
        "AAPL": market_result(
            "AAPL",
            {
                "2026-09-14": 100,
                "2026-09-15": 110,
            },
        ),
        "MSFT": market_result(
            "MSFT",
            {
                "2026-09-14": 200,
                "2026-09-15": 200,
            },
        ),
    }

    result = (
        EqualWeightBenchmarkService(
            market_data_fetcher=(
                lambda symbol:
                data[
                    symbol
                ]
            ),
            symbols=[
                "AAPL",
                "MSFT",
            ],
        )
        .compare(
            [
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
                    "10600",
                ),
            ]
        )
    )

    assert (
        result.model_total_return_pct
        == Decimal(
            "6.00"
        )
    )

    assert (
        result.benchmark_total_return_pct
        == Decimal(
            "5.00"
        )
    )

    assert (
        result.excess_return_pct
        == Decimal(
            "1.00"
        )
    )


def test_missing_session_rejected():

    data = {
        "AAPL": market_result(
            "AAPL",
            {
                "2026-09-14": 100,
            },
        ),
    }

    service = (
        EqualWeightBenchmarkService(
            market_data_fetcher=(
                lambda symbol:
                data[
                    symbol
                ]
            ),
            symbols=[
                "AAPL",
            ],
        )
    )

    with pytest.raises(
        EqualWeightBenchmarkError
    ):

        service.compare(
            [
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
        )


def test_missing_adjusted_close_rejected():

    bad = MarketDataResult(
        ticker="AAPL",
        data=pd.DataFrame(
            {
                "Close": [
                    100,
                ],
            },
            index=pd.to_datetime(
                [
                    "2026-09-14",
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

    service = (
        EqualWeightBenchmarkService(
            market_data_fetcher=(
                lambda symbol:
                bad
            ),
            symbols=[
                "AAPL",
            ],
        )
    )

    with pytest.raises(
        EqualWeightBenchmarkError
    ):

        service.compare(
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


def test_nonpositive_price_rejected():

    data = market_result(
        "AAPL",
        {
            "2026-09-14": 0,
        },
    )

    service = (
        EqualWeightBenchmarkService(
            market_data_fetcher=(
                lambda symbol:
                data
            ),
            symbols=[
                "AAPL",
            ],
        )
    )

    with pytest.raises(
        EqualWeightBenchmarkError
    ):

        service.compare(
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


def test_history_sorted_before_comparison():

    data = {
        "AAPL": market_result(
            "AAPL",
            {
                "2026-09-14": 100,
                "2026-09-15": 105,
            },
        ),
    }

    result = (
        EqualWeightBenchmarkService(
            market_data_fetcher=(
                lambda symbol:
                data[
                    symbol
                ]
            ),
            symbols=[
                "AAPL",
            ],
        )
        .compare(
            [
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
        )
    )

    assert [
        point.session
        for point
        in result.points
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