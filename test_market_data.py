from services.data_quality import validate_market_data
from services.market_data import get_market_data


result = get_market_data(
    ticker="AAPL",
    period="6mo",
)

report = validate_market_data(result)


print()
print("MARKET DATA HEALTH CHECK")
print("------------------------")

print(f"Ticker: {result.ticker}")
print(f"Provider: {result.provider}")
print(f"Rows: {len(result.data)}")

print(
    "Latest data session:",
    report.latest_data_session,
)

print(
    "Latest expected completed session:",
    report.latest_expected_completed_session,
)

print(
    "Safe to use:",
    report.safe_to_use,
)

print()
print("QUALITY REPORT")
print("------------------------")

for issue in report.issues:
    print(
        f"[{issue.severity.value}] "
        f"{issue.code}: "
        f"{issue.message}"
    )