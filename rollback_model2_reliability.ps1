# Preview by default; restores the exact exported definitions, not database state.
param([Parameter(Mandatory=$true)][string]$BackupDirectory,[switch]$Apply)
$ErrorActionPreference='Stop'
$names=[ordered]@{
 execution='Paper Trading - Model 2 Guarded Execution'
 decision='Paper Trading - Model 2 Daily Decision'
 snapshot='Paper Trading - Model 2 Equity Snapshot'
 closing='Paper Trading - Model 2 Daily Equity'
 cleanup='Paper Trading - Model 2 Stale Order Cleanup'
}
foreach ($kind in $names.Keys) {
    $file=Join-Path $BackupDirectory ($kind+'.xml')
    if (-not (Test-Path $file)) { throw "Missing backup: $file" }
    if ((Get-ScheduledTask -TaskName $names[$kind] -TaskPath '\').State -eq 'Running') { throw "Task currently running: $($names[$kind])" }
    Write-Host "Restore $($names[$kind]) from $file"
}
if (-not $Apply) { Write-Host 'PREVIEW ONLY'; return }
foreach ($kind in $names.Keys) {
    $file=Join-Path $BackupDirectory ($kind+'.xml')
    Register-ScheduledTask -TaskName $names[$kind] -TaskPath '\' -Xml (Get-Content $file -Raw) -Force | Out-Null
}
Write-Host 'Definitions restored. No tasks explicitly started.'
