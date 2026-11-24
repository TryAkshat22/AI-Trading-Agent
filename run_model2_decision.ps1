$ErrorActionPreference = "Stop"

$ProjectPath = "C:\Users\rkjan\OneDrive\Documents\PaperTradingAgent"
$PythonPath = Join-Path $ProjectPath ".venv\Scripts\python.exe"
$DecisionPath = Join-Path $ProjectPath "model2_decision_command.py"

$LogDirectory = Join-Path $ProjectPath "logs"
$LogFile = Join-Path $LogDirectory "scheduled_model2_decision.log"

New-Item -ItemType Directory -Force -Path $LogDirectory | Out-Null

Set-Location $ProjectPath

$Timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz"

"==================================================" | Out-File $LogFile -Append
"Model 2 decision started: $Timestamp" |
    Out-File $LogFile -Append

try {

    if (-not (Test-Path $PythonPath)) {
        throw "Python executable not found: $PythonPath"
    }

    if (-not (Test-Path $DecisionPath)) {
        throw "Decision command not found: $DecisionPath"
    }

    & $PythonPath `
        $DecisionPath `
        --run `
        *>> $LogFile

    $ExitCode = $LASTEXITCODE

    "Decision exit code: $ExitCode" |
        Out-File $LogFile -Append

    if ($ExitCode -ne 0) {
        "MODEL 2 DECISION BLOCKED OR FAILED." |
            Out-File $LogFile -Append

        exit $ExitCode
    }

    "MODEL 2 DECISION COMPLETED SUCCESSFULLY." |
        Out-File $LogFile -Append

    exit 0
}
catch {

    "ERROR: $($_.Exception.Message)" |
        Out-File $LogFile -Append

    exit 1
}