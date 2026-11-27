param([Parameter(Mandatory=$true)][ValidateSet('execution','decision','snapshot','closing','cleanup')][string]$Task)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$logDir = Join-Path $PSScriptRoot 'logs'
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
$logNames = @{execution='scheduled_model2_execution.log'; decision='scheduled_model2_decision.log'; snapshot='model2_equity_snapshot.log'; closing='model2_daily_equity.log'; cleanup='scheduled_model2_expiry.log'}
$log = Join-Path $logDir $logNames[$Task]
Add-Content $log "`n=== $(Get-Date -Format o) ==="
try {
    if (-not (Test-Path $python)) { throw 'Python executable missing' }
    $ErrorActionPreference = 'Continue'
    & $python -u -m model2_reliability.runner $Task --apply 2>&1 | ForEach-Object { Add-Content $log ([string]$_) }
    $code = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'
    Add-Content $log "Exit code: $code"
    exit $code
} catch {
    Add-Content $log "WRAPPER ERROR: $_"
    exit 1
}
