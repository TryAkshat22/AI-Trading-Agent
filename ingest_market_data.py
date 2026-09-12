from database.storage import (
    MarketDataStorage,
)
from services.data_quality import (
    validate_market_data,
)
from services.market_data import (
    get_market_data,
)


TICKER = "AAPL"


print()
print("MARKET DATA INGESTION")
print("------------------------")


market_result = get_market_data(
    ticker=TICKER,
    period="6mo",
)

print(
    f"Retrieved "
    f"{len(market_result.data)} "
    f"rows for {TICKER}."
)


quality_report = validate_market_data(
    market_result
)

print(
    f"Safe to use: "
    f"{quality_report.safe_to_use}"
)


if not quality_report.safe_to_use:

    print()
    print(
        "INGESTION HALTED."
    )

    for issue in quality_report.issues:
        print(
            f"[{issue.severity.value}] "
            f"{issue.code}: "
            f"{issue.message}"
        )

    raise SystemExit(1)


storage = MarketDataStorage()

storage.initialize()


save_result = (
    storage.save_market_snapshot(
        result=market_result,
        quality_report=quality_report,
    )
)


print()
print("SNAPSHOT SAVED")
print("------------------------")

print(
    f"Run ID: "
    f"{save_result.run_id}"
)

print(
    f"Rows saved: "
    f"{save_result.rows_saved}"
)

print(
    f"Database: "
    f"{save_result.database_path}"
)