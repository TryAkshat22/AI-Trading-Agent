$ErrorActionPreference = "Stop"

$ProjectPath = "C:\Users\rkjan\OneDrive\Documents\PaperTradingAgent"
$Python = Join-Path $ProjectPath ".venv\Scripts\python.exe"
$Agent = Join-Path $ProjectPath "model2_agent_ui.py"

Set-Location $ProjectPath

& $Python $Agent
