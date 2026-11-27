$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$script = Join-Path $PSScriptRoot "model2_equity_snapshot.py"
$logDir = Join-Path $PSScriptRoot "logs"
$logFile = Join-Path $logDir "model2_equity_snapshot.log"

New-Item -ItemType Directory -Path $logDir -Force |
    Out-Null

Add-Content $logFile "`n=== $(Get-Date -Format o) ==="

& $python $script --save >> $logFile 2>&1

$result = $LASTEXITCODE
Add-Content $logFile "Exit code: $result"

exit $result