$ErrorActionPreference = "Stop"

$ProjectPath = "C:\Users\rkjan\OneDrive\Documents\PaperTradingAgent"
$PythonPath = Join-Path $ProjectPath ".venv\Scripts\python.exe"
$ScriptPath = Join-Path $ProjectPath "model2_auto_expire_stale_orders.py"
$LogDirectory = Join-Path $ProjectPath "logs"
$LogFile = Join-Path $LogDirectory "scheduled_model2_expiry.log"

New-Item `
    -ItemType Directory `
    -Force `
    -Path $LogDirectory |
    Out-Null

Set-Location $ProjectPath

"==================================================" |
    Out-File $LogFile -Append

"Model 2 automatic expiry started: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss zzz')" |
    Out-File $LogFile -Append

try {

    if (-not (Test-Path $PythonPath)) {
        throw "Python executable not found: $PythonPath"
    }

    if (-not (Test-Path $ScriptPath)) {
        throw "Auto-expiry script not found: $ScriptPath"
    }

    & $PythonPath $ScriptPath *>> $LogFile

    $ExitCode = $LASTEXITCODE

    "Auto-expiry exit code: $ExitCode" |
        Out-File $LogFile -Append

    if ($ExitCode -ne 0) {

        "MODEL 2 AUTO EXPIRY FAILED." |
            Out-File $LogFile -Append

        exit $ExitCode
    }

    "MODEL 2 AUTO EXPIRY COMPLETED SUCCESSFULLY." |
        Out-File $LogFile -Append

    exit 0
}
catch {

    "ERROR: $($_.Exception.Message)" |
        Out-File $LogFile -Append

    exit 1
}