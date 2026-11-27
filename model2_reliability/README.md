# Model 2 reliability update

Apply only to the Nov 27 Stage 3 intelligence update (baseline commit 475b6e3 plus Stage 3). New code is inactive until scheduler actions are changed. Existing Model 1 and shared intraday task, trading engines, strategy and database schemas are not modified. The two replaced files are `model2_intelligence/service.py` and `model2_web/app.py` from Stage 3.

## Verify before applying

1. Extract into the existing project. Run `.\.venv\Scripts\python.exe -m pytest .\tests\test_model2_reliability.py .\tests\test_model2_intelligence.py .\tests\test_model2_web_data.py -q` (30 expected).
2. Run `.\.venv\Scripts\python.exe -m model2_reliability.maintenance` for a read-only historical closing recovery preview. No downloads or writes in preview.
3. Run `powershell -NoProfile -ExecutionPolicy Bypass -File .\install_model2_reliability.ps1` for task preview. It requires Eastern Windows timezone and supported existing principals. If permissions fail, inspect from an elevated terminal; do not change credentials or principals. The preview constructs the new triggers but does not register them.
4. Review preview and tests before running `powershell -NoProfile -ExecutionPolicy Bypass -File .\install_model2_reliability.ps1 -Apply`. Apply when no task is running, ideally outside execution hours. Existing triggers can still fire during installation; do not manually start tasks. No task is explicitly started by the installer, but Windows may automatically launch due tasks.
5. Verify task actions, triggers, repetition, settings and next run times in Task Scheduler. Restart local Streamlit if needed to load the two Python updates.

## Behavior

- Execution starts at 09:50 on weekdays and repeats every 15 minutes; the real NYSE calendar and existing guarded executor remain authoritative. More opportunities are provided for missed starts. No same-day retry after a recorded execution failure or unfinished start: inspection is required. Runs interrupted before an outcome marker is recorded still rely on the original engine preflight. No stale orders are rescheduled or executed retroactively.
- Cleanup runs 09:35 and 20:45 and may run on battery. The existing expiry engine expires **past dates only**, recording `REJECTED` with `EXECUTION_WINDOW_EXPIRED`. The Nov 27 orders cannot expire via this engine until the date advances. Same-day post-cutoff pending orders are shown by the audit.
- Decision and maintenance attempt early-close-friendly and regular post-close starts. The existing ledger prevents re-running completed or failed claimed decisions. No strategy logic is changed. A failed decision can need manual inspection rather than automatic retry.
- Maintenance reconstructs only missing sessions from exact-session safe, post-close retrieved marks already stored in the Model 2 database, using existing closing valuation code. Existing backfill and verified closes are preserved. Missing marks remain missing. This does **not** fetch missing individual equity marks from the provider.
- SPY adjusted closes are collected separately via the already installed yfinance dependency. Full expected session coverage and positive finite values are required before atomically replacing `model2_spy_benchmark.csv` beside the Model 2 trading DB. Yahoo Finance is not independently verified and can delay or revise data. Benchmark is never loaded in demo mode. Explicit `MODEL2_BENCHMARK_CSV` and `MODEL2_BENCHMARK_LABEL` override auto-detection. Risk-free rate is still an explicit assumption, not automatically invented.
- Structured local JSONL outcome logs are written under `logs/` (ignored by Git). Normal calendar/no-order/completed-ledger skips return zero; incomplete closing recovery is separately labeled; errors retain nonzero exit codes. Existing child commands do not reliably distinguish every blocker from failure, so `BLOCKED_OR_FAILED` is used rather than guessing. Shared intraday logs remain as before. The health page and service show recorded outcomes, last non-skip outcome, closing coverage and pending/expired orders past the cutoff. No scheduler availability guarantee.

## Rollback

Installer exports five original task XML definitions to `logs/reliability-task-backup-<timestamp>/`. It attempts to restore original actions/triggers/settings if an update fails. To restore exact original XML, first preview `powershell -NoProfile -ExecutionPolicy Bypass -File .\rollback_model2_reliability.ps1 -BackupDirectory '<actual backup folder>'`, then add `-Apply` only after confirming. Task registration permissions may require elevation. Rollback does not undo valid portfolio records or valuations already written. Restore the two replaced dashboard/service files from the prior Stage 3 ZIP if desired. Keep all logs and backups private.

## Verification limitations

Python tests use synthetic fixtures and the installed exchange calendar. Windows Task Scheduler and PowerShell scripts cannot be executed in the build environment; actual trigger registration, live yfinance retrieval, task outcomes, Streamlit runtime, and the full regression suite must be verified on the laptop. No remote MCP or live LLM access is added by this package.
