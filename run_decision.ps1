$ErrorActionPreference = "Stop"

$ProjectPath = "C:\Users\rkjan\OneDrive\Documents\PaperTradingAgent"
$PythonPath = Join-Path $ProjectPath ".venv\Scripts\python.exe"
$LogDirectory = Join-Path $ProjectPath "logs"
$LogFile = Join-Path $LogDirectory "scheduled_decision.log"

New-Item -ItemType Directory -Force -Path $LogDirectory | Out-Null

Set-Location $ProjectPath

$Timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

"==================================================" | Out-File $LogFile -Append
"Decision task started: $Timestamp" | Out-File $LogFile -Append

try {
    & $PythonPath app.py decision *>> $LogFile

    $ExitCode = $LASTEXITCODE

    "Decision exit code: $ExitCode" | Out-File $LogFile -Append

    if ($ExitCode -ne 0) {
        "Decision task FAILED." | Out-File $LogFile -Append
        exit $ExitCode
    }

    "Decision task completed successfully." | Out-File $LogFile -Append
}
catch {
    "ERROR: $($_.Exception.Message)" | Out-File $LogFile -Append
    exit 1
}