from __future__ import annotations


MODEL2_TICKERS = (
    "AAPL",
    "MSFT",
    "NVDA",
    "AVGO",
    "GOOGL",
    "META",
    "AMZN",
    "TSLA",
    "PLTR",
    "ORCL",

    "AMD",
    "MU",
    "TSM",
    "QCOM",

    "ASML",
    "LRCX",
    "AMAT",
    "KLAC",
    "LITE",

    "VRT",
    "ETN",
    "EQIX",
    "DLR",
    "CEG",
    "VST",
    "GEV",

    "JPM",
    "BAC",
    "C",
    "WFC",
    "GS",
    "MS",

    "JNJ",
    "LLY",
    "UNH",
    "ABBV",

    "XOM",
    "CVX",
    "COP",

    "CAT",
    "GE",
    "HON",

    "WMT",
    "COST",
    "HD",
    "NFLX",

    "LIN",
    "NUE",
    "PG",
    "NEE",
)


MODEL2_GROUPS = {
    "AAPL": "Mega-cap Tech / AI",
    "MSFT": "Mega-cap Tech / AI",
    "NVDA": "Mega-cap Tech / AI",
    "AVGO": "Mega-cap Tech / AI",
    "GOOGL": "Mega-cap Tech / AI",
    "META": "Mega-cap Tech / AI",
    "AMZN": "Mega-cap Tech / AI",
    "TSLA": "Mega-cap Tech / AI",
    "PLTR": "Mega-cap Tech / AI",
    "ORCL": "Mega-cap Tech / AI",

    "AMD": "Semiconductors",
    "MU": "Semiconductors",
    "TSM": "Semiconductors",
    "QCOM": "Semiconductors",

    "ASML": "Semiconductor Equipment",
    "LRCX": "Semiconductor Equipment",
    "AMAT": "Semiconductor Equipment",
    "KLAC": "Semiconductor Equipment",
    "LITE": "Semiconductor Equipment",

    "VRT": "Data Center Infrastructure",
    "ETN": "Data Center Infrastructure",
    "EQIX": "Data Center Infrastructure",
    "DLR": "Data Center Infrastructure",
    "CEG": "Data Center Infrastructure",
    "VST": "Data Center Infrastructure",
    "GEV": "Data Center Infrastructure",

    "JPM": "Financials",
    "BAC": "Financials",
    "C": "Financials",
    "WFC": "Financials",
    "GS": "Financials",
    "MS": "Financials",

    "JNJ": "Health Care",
    "LLY": "Health Care",
    "UNH": "Health Care",
    "ABBV": "Health Care",

    "XOM": "Energy",
    "CVX": "Energy",
    "COP": "Energy",

    "CAT": "Industrials",
    "GE": "Industrials",
    "HON": "Industrials",

    "WMT": "Consumer",
    "COST": "Consumer",
    "HD": "Consumer",
    "NFLX": "Consumer",

    "LIN": "Materials / Defensive",
    "NUE": "Materials / Defensive",
    "PG": "Materials / Defensive",
    "NEE": "Materials / Defensive",
}


if len(MODEL2_TICKERS) != 50:
    raise RuntimeError(
        "Model 2 universe must contain exactly 50 tickers."
    )


if len(set(MODEL2_TICKERS)) != len(MODEL2_TICKERS):
    raise RuntimeError(
        "Model 2 universe contains duplicate tickers."
    )


if set(MODEL2_TICKERS) != set(MODEL2_GROUPS):
    raise RuntimeError(
        "Model 2 group mapping does not match "
        "the ticker universe."
    )