# Model 2 Intelligence | Stage 3A–3C

Base: `475b6e3abc0179bde9e7b57fafcd4a57dd0900c0`.

This additive update uses the existing saved performance reader and exchange-session chart logic. It replaces the web risk calculation with a shared implementation and adds a local stdio MCP adapter. It does not modify either trading strategy, scheduled tasks, order creation, execution code, or database schema. It does not write valuations.

## Install and test

From the repository root, with a clean working tree at the stated base, extract the update ZIP into the repository root. Review `git status --short` before committing. Do not publish benchmark files or actual database exports. Run:

```powershell
.\.venv\Scripts\python.exe -m pytest .\tests\test_model2_intelligence.py .\tests\test_model2_web_data.py -q
.\.venv\Scripts\python.exe -m pytest .\tests -q
```

The new analytics module uses pandas and exchange_calendars already required by the dashboard. Do not reinstall or upgrade the trading environment just to test this update.

## Demo and local mode

```powershell
$env:MODEL2_WEB_MODE = 'demo'
.\.venv\Scripts\python.exe -c "from model2_intelligence.service import Intelligence; import json; print(json.dumps(Intelligence.from_env().get_performance(), indent=2, allow_nan=False))"
$env:MODEL2_WEB_MODE = 'local'
$env:MODEL2_PERFORMANCE_DB = "$env:LOCALAPPDATA\PaperTradingAgent\model2_performance.db"
.\.venv\Scripts\python.exe -c "from model2_intelligence.service import Intelligence; import json; print(json.dumps(Intelligence.from_env().get_portfolio(), indent=2, allow_nan=False))"
.\.venv\Scripts\python.exe -m streamlit run .\model2_web\app.py --server.address 127.0.0.1
```

`PAPER_TRADING_MODEL2_DB_PATH` optionally overrides the sibling trading database path. Local mode never falls back to demo. Positions are only available when matching intraday marks reconcile to the saved invested amount and position count. Daily records and intraday marks are different types of valuations. Do not interpret the latest saved observation as a live quote. All percentages returned by the risk and benchmark metrics are **decimal fractions**; `exposure_pct`, `group_weights_pct` and the existing saved `total_return_pct` are percentage points. Closing metrics exclude intraday observations. Missing internal sessions are not filled or bridged for daily returns; drawdown is based on observed closes. The selected time window may have incomplete endpoints, so the actual first and last observation dates are returned. No cash-flow adjustments are made (fixed starting-capital paper account).

## Benchmark and risk-free configuration

No market data is downloaded by this package. Obtain a trusted adjusted-close series separately (e.g. SPY, a proxy for the S&P 500, not the index itself). Store the CSV outside the repository, using exactly the following headers and one row per exchange session:

```text
session_date,adjusted_close
```

Set `MODEL2_BENCHMARK_CSV` to its path and `MODEL2_BENCHMARK_LABEL` to its precise instrument/source label. The input's provenance is user-supplied and not independently verified. Demo mode never uses this actual benchmark. `MODEL2_ANNUAL_RF` is an optional annual effective risk-free assumption as a decimal fraction, e.g. `0.04` means 4% (illustrative assumption, not a current market rate). Without it, Sharpe, Sortino and Jensen alpha are unavailable. Volatility and beta require at least 20 adjacent returns; zero denominators yield unavailable ratios. No automatic annualized cumulative return is reported for short or incomplete histories.

## MCP (optional, local only)

The SDK is an optional dependency. Keep it separate from the trading environment until compatibility has been checked. Example using a separate virtual environment outside the repository:

```powershell
$intelEnv = "$env:LOCALAPPDATA\PaperTradingAgent\intelligence-venv"
.\.venv\Scripts\python.exe -m venv $intelEnv
$intelPython = Join-Path $intelEnv 'Scripts\python.exe'
& $intelPython -m pip install 'pandas>=2,<4' 'exchange-calendars>=4.13,<5' tzdata -r .\model2_intelligence\requirements.txt
& $intelPython -m model2_intelligence.mcp_server
```

The last command starts a stdio protocol server and waits for an MCP client; it is not a conversational console. Stop it with Ctrl+C when testing. Client launch must use repository root as working directory and explicitly configured environment variables. Tools accept fixed period/limit arguments, never caller-provided paths or SQL. There is no HTTP listener, remote authentication, or GitHub cloud connection. Do not port-forward or expose this server publicly. MCP SDK installation and handshake have not been tested in the packaging environment. The existing web analyst remains scripted; remote LLM integration, persisted signal export, trade explanations, market movers in MCP, and authenticated cloud deployment are future stages. The terminal agent remains unchanged.

## Verification

In the packaging environment, the nine new unit tests and three existing web data tests passed. Python syntax compilation succeeded. The full repository regression suite, Streamlit runtime and MCP SDK transport were not tested here because the environment lacks their dependencies. Run full regression and local interface tests on Windows before publishing. The baseline previously passed 587 tests; with these nine tests, the expected collection count is 596 if no other changes have occurred.
