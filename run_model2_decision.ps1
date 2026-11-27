$ErrorActionPreference = "Stop"

$ProjectPath = $PSScriptRoot
$PythonPath = Join-Path $ProjectPath ".venv\Scripts\python.exe"
$DecisionPath = Join-Path $ProjectPath "model2_decision_command.py"

$LogDirectory = Join-Path $ProjectPath "logs"
$LogFile = Join-Path $LogDirectory "scheduled_model2_decision.log"

New-Item -ItemType Directory -Force -Path $LogDirectory | Out-Null
Set-Location $ProjectPath

function Write-DecisionLog {
    param([string]$Message)
    Add-Content -Path $LogFile -Value $Message
}

Write-DecisionLog "=================================================="
Write-DecisionLog "Model 2 decision started: $(Get-Date -Format o)"
Write-DecisionLog "UTC time: $([DateTime]::UtcNow.ToString('o'))"

try {
    if (-not (Test-Path $PythonPath)) {
        throw "Python executable not found: $PythonPath"
    }

    if (-not (Test-Path $DecisionPath)) {
        throw "Decision command not found: $DecisionPath"
    }

    $ErrorActionPreference = "Continue"

    & $PythonPath -u $DecisionPath --run 2>&1 |
        ForEach-Object {
            Write-DecisionLog ([string]$_)
        }

    $ExitCode = $LASTEXITCODE
    $ErrorActionPreference = "Stop"

    Write-DecisionLog "Decision exit code: $ExitCode"
    Write-DecisionLog "Finished: $(Get-Date -Format o)"

    if ($ExitCode -ne 0) {
        Write-DecisionLog "MODEL 2 DECISION BLOCKED OR FAILED."
        exit $ExitCode
    }

    Write-DecisionLog "MODEL 2 DECISION COMPLETED SUCCESSFULLY."
    exit 0
}
catch {
    Write-DecisionLog "WRAPPER ERROR: $($_ | Out-String)"
    exit 1
}