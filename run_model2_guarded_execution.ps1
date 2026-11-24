$ErrorActionPreference = "Stop"

$ProjectPath = "C:\Users\rkjan\OneDrive\Documents\PaperTradingAgent"
$PythonPath = Join-Path $ProjectPath ".venv\Scripts\python.exe"
$ExecutionPath = Join-Path $ProjectPath "model2_guarded_execution_command.py"

$LogDirectory = Join-Path $ProjectPath "logs"
$LogFile = Join-Path $LogDirectory "scheduled_model2_execution.log"

New-Item -ItemType Directory -Force -Path $LogDirectory | Out-Null

Set-Location $ProjectPath

$Session = Get-Date -Format "yyyy-MM-dd"
$Timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz"

"==================================================" |
    Out-File $LogFile -Append

"Model 2 guarded execution started: $Timestamp" |
    Out-File $LogFile -Append

"Execution session: $Session" |
    Out-File $LogFile -Append

try {

    if (-not (Test-Path $PythonPath)) {
        throw "Python executable not found: $PythonPath"
    }

    if (-not (Test-Path $ExecutionPath)) {
        throw "Execution command not found: $ExecutionPath"
    }

    # Native programs legitimately use stderr for error details.
    # Do not let PowerShell convert those lines into a terminating
    # PowerShell exception before Python finishes reporting the
    # actual blocker.
    $PreviousPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"

    try {
        & $PythonPath `
            $ExecutionPath `
            --session $Session `
            --execute-paper `
            --confirm MODEL2-PAPER `
            2>&1 |
            ForEach-Object {
                $_.ToString() |
                    Out-File $LogFile -Append
            }

        $ExitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $PreviousPreference
    }

    "Execution exit code: $ExitCode" |
        Out-File $LogFile -Append

    if ($ExitCode -ne 0) {
        "MODEL 2 EXECUTION BLOCKED OR FAILED." |
            Out-File $LogFile -Append

        exit $ExitCode
    }

    "MODEL 2 EXECUTION COMPLETED SUCCESSFULLY." |
        Out-File $LogFile -Append

    exit 0
}
catch {

    "WRAPPER ERROR: $($_.Exception.Message)" |
        Out-File $LogFile -Append

    exit 1
}