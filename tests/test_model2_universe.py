from model2_universe import (
    MODEL2_GROUPS,
    MODEL2_TICKERS,
)

from collect_intraday import TICKERS
from model2_decision_runner import MODEL_2_TICKERS


def test_model2_universe_contains_50_unique_tickers():
    assert len(MODEL2_TICKERS) == 50
    assert len(set(MODEL2_TICKERS)) == 50


def test_collector_uses_central_model2_universe():
    assert TICKERS == MODEL2_TICKERS


def test_decision_runner_uses_central_model2_universe():
    assert MODEL_2_TICKERS == MODEL2_TICKERS


def test_every_model2_ticker_has_group():
    assert set(MODEL2_TICKERS) == set(MODEL2_GROUPS)


def test_all_group_names_are_non_empty():
    for ticker in MODEL2_TICKERS:
        assert isinstance(MODEL2_GROUPS[ticker], str)
        assert MODEL2_GROUPS[ticker].strip()


def test_model2_universe_contains_original_10_tickers():
    original = {
        "AAPL",
        "MSFT",
        "NVDA",
        "AMZN",
        "GOOGL",
        "META",
        "JPM",
        "XOM",
        "JNJ",
        "WMT",
    }

    assert original.issubset(
        set(MODEL2_TICKERS)
    )


def test_model2_universe_contains_major_banks():
    expected = {
        "JPM",
        "BAC",
        "C",
        "WFC",
        "GS",
        "MS",
    }

    assert expected.issubset(
        set(MODEL2_TICKERS)
    )


def test_model2_universe_contains_semiconductors():
    expected = {
        "NVDA",
        "AVGO",
        "AMD",
        "MU",
        "TSM",
        "QCOM",
    }

    assert expected.issubset(
        set(MODEL2_TICKERS)
    )


def test_model2_universe_contains_semiconductor_equipment():
    expected = {
        "ASML",
        "LRCX",
        "AMAT",
        "KLAC",
        "LITE",
    }

    assert expected.issubset(
        set(MODEL2_TICKERS)
    )


def test_model2_universe_contains_data_center_infrastructure():
    expected = {
        "VRT",
        "ETN",
        "EQIX",
        "DLR",
        "CEG",
        "VST",
        "GEV",
    }

    assert expected.issubset(
        set(MODEL2_TICKERS)
    )


def test_model2_universe_has_broad_group_coverage():
    expected_groups = {
        "Mega-cap Tech / AI",
        "Semiconductors",
        "Semiconductor Equipment",
        "Data Center Infrastructure",
        "Financials",
        "Health Care",
        "Energy",
        "Industrials",
        "Consumer",
        "Materials / Defensive",
    }

    assert set(
        MODEL2_GROUPS.values()
    ) == expected_groups