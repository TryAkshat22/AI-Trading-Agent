$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$script = Join-Path $PSScriptRoot "model2_daily_equity.py"
$logDir = Join-Path $PSScriptRoot "logs"
$logFile = Join-Path $logDir "model2_daily_equity.log"

New-Item -ItemType Directory -Path $logDir -Force |
    Out-Null

Add-Content $logFile "`n=== $(Get-Date -Format o) ==="

try {
    $ErrorActionPreference = "Continue"

    & $python -u $script --save 2>&1 |
        ForEach-Object {
            Add-Content $logFile ([string]$_)
        }

    $result = $LASTEXITCODE
    $ErrorActionPreference = "Stop"

    Add-Content $logFile "Exit code: $result"

    exit $result
}
catch {
    Add-Content $logFile "WRAPPER ERROR: $_"
    exit 1
}