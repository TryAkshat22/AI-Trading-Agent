$ErrorActionPreference = "Stop"

$ProjectPath = "C:\Users\rkjan\OneDrive\Documents\PaperTradingAgent"
$PythonPath = Join-Path $ProjectPath ".venv\Scripts\python.exe"
$LogDirectory = Join-Path $ProjectPath "logs"
$LogFile = Join-Path $LogDirectory "scheduled_execution.log"

New-Item -ItemType Directory -Force -Path $LogDirectory | Out-Null

Set-Location $ProjectPath

$Session = Get-Date -Format "yyyy-MM-dd"
$Timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

"==================================================" | Out-File $LogFile -Append
"Execution task started: $Timestamp" | Out-File $LogFile -Append
"Execution session: $Session" | Out-File $LogFile -Append

try {
    "Running readiness check..." | Out-File $LogFile -Append

    & $PythonPath app.py execution-check --session $Session *>> $LogFile

    $ReadinessExitCode = $LASTEXITCODE

    if ($ReadinessExitCode -ne 0) {
        "Readiness check blocked execution." | Out-File $LogFile -Append
        "Execution was NOT attempted." | Out-File $LogFile -Append
        exit 0
    }

    "Readiness check passed." | Out-File $LogFile -Append
    "Starting execution..." | Out-File $LogFile -Append

    & $PythonPath app.py execution --session $Session *>> $LogFile

    $ExecutionExitCode = $LASTEXITCODE

    "Execution exit code: $ExecutionExitCode" | Out-File $LogFile -Append

    if ($ExecutionExitCode -ne 0) {
        "Execution task FAILED." | Out-File $LogFile -Append
        exit $ExecutionExitCode
    }

    "Execution task completed successfully." | Out-File $LogFile -Append
}
catch {
    "ERROR: $($_.Exception.Message)" | Out-File $LogFile -Append
    exit 1
}