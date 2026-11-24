
from __future__ import annotations
from model2_universe import MODEL2_TICKERS

TICKERS = MODEL2_TICKERS

import argparse
import sys

from services.intraday_collector import (
    IntradayObservationStorage,
    YahooIntradayCollector,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Collect intraday research observations without trading."
    )
    parser.add_argument(
        "--collect",
        action="store_true",
        help="Explicitly authorize one collection batch.",
    )
    args = parser.parse_args()

    if not args.collect:
        parser.print_help()
        return 0

    storage = IntradayObservationStorage()
    storage.initialize()

    collector = YahooIntradayCollector(storage=storage)
    result = collector.collect_batch(TICKERS)

    print("Intraday collection")
    print("===================")

    for outcome in result.outcomes:
        if outcome.error:
            print(f"{outcome.ticker}: FAILED — {outcome.error}")
        elif outcome.saved:
            print(f"{outcome.ticker}: SAVED")
        else:
            print(f"{outcome.ticker}: ALREADY STORED")

    print()
    print(f"New observations: {result.saved}")
    print(f"Failures: {result.failed}")
    print(f"Total stored observations: {storage.count()}")

    return 1 if result.failed else 0


if __name__ == "__main__":
    sys.exit(main())