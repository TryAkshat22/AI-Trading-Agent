
$ErrorActionPreference = "Stop"

$ProjectPath = "C:\Users\rkjan\OneDrive\Documents\PaperTradingAgent"
$PythonPath = Join-Path $ProjectPath ".venv\Scripts\python.exe"
$CollectorPath = Join-Path $ProjectPath "collect_intraday.py"
$LogDirectory = Join-Path $ProjectPath "logs"
$LogFile = Join-Path $LogDirectory "scheduled_intraday.log"

New-Item -ItemType Directory -Force -Path $LogDirectory | Out-Null

Set-Location $ProjectPath

"==================================================" | Out-File $LogFile -Append
"Collection task started: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss zzz')" |
    Out-File $LogFile -Append

try {
    if (-not (Test-Path $PythonPath)) {
        throw "Python executable not found: $PythonPath"
    }

    if (-not (Test-Path $CollectorPath)) {
        throw "Collector file not found: $CollectorPath"
    }

    & $PythonPath $CollectorPath --collect *>> $LogFile

    $ExitCode = $LASTEXITCODE

    "Collection exit code: $ExitCode" | Out-File $LogFile -Append

    if ($ExitCode -ne 0) {
        "Collection task FAILED." | Out-File $LogFile -Append
        exit $ExitCode
    }

    "Collection task completed successfully." |
        Out-File $LogFile -Append

    exit 0
}
catch {
    "ERROR: $($_.Exception.Message)" | Out-File $LogFile -Append
    exit 1
}