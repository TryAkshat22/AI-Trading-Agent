$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

$env:MODEL2_WEB_MODE = "local"
$env:PYTHONPATH = $PSScriptRoot
$env:MODEL2_PERFORMANCE_DB = "$env:LOCALAPPDATA\PaperTradingAgent\model2_performance.db"

if (-not (Test-Path $env:MODEL2_PERFORMANCE_DB)) {
    throw "Local performance database not found."
}

& "$PSScriptRoot\.venv\Scripts\python.exe" -u -m model2_intelligence.mcp_server

exit $LASTEXITCODE