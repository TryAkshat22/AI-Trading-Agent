# Preview by default. Does not start any scheduled task.
param([switch]$Apply)
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
if ((Get-TimeZone).Id -ne 'Eastern Standard Time') { throw 'This schedule assumes Windows Eastern time. No changes made.' }
if (-not (Test-Path (Join-Path $root '.venv\Scripts\python.exe'))) { throw 'Project Python missing.' }
$names = [ordered]@{
 'Paper Trading - Model 2 Guarded Execution'='execution'
 'Paper Trading - Model 2 Daily Decision'='decision'
 'Paper Trading - Model 2 Equity Snapshot'='snapshot'
 'Paper Trading - Model 2 Daily Equity'='closing'
 'Paper Trading - Model 2 Stale Order Cleanup'='cleanup'
}
$old = @{}
foreach ($name in $names.Keys) {
    $t = Get-ScheduledTask -TaskName $name -TaskPath '\'
    if ($t.State -eq 'Running') { throw "Task running: $name. Do not apply during active work." }
    if ($t.Principal.LogonType -notin @('S4U','Interactive','InteractiveToken','ServiceAccount')) { throw "Unsupported task logon type: $($t.Principal.LogonType). No changes made." }
    $old[$name] = $t
}
Write-Host 'Proposed schedule (Eastern local time; calendar checked by Python):'
Write-Host 'Execution: weekdays 09:50, repeat 15m for 5h40m (last eligible regular start 15:20).'
Write-Host 'Decision: 13:20, 16:20, 18:20, 20:20. Closing maintenance: 13:40, 16:40, 18:40, 20:40.'
Write-Host 'Snapshot: keep existing triggers. Cleanup: 09:35 and 20:45, including battery.'
Write-Host 'Shared intraday collection and Model 1 tasks unchanged.'
function Weekly([string]$At) {
    New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At ([datetime]::Today.Add([timespan]::Parse($At)))
}
$execution = Weekly '09:50'
$execution.Repetition = New-CimInstance -Namespace 'Root/Microsoft/Windows/TaskScheduler' -ClassName MSFT_TaskRepetitionPattern -ClientOnly -Property @{Interval='PT15M';Duration='PT5H40M';StopAtDurationEnd=$false}
$triggers = @{
 execution=@($execution)
 decision=@((Weekly '13:20'),(Weekly '16:20'),(Weekly '18:20'),(Weekly '20:20'))
 closing=@((Weekly '13:40'),(Weekly '16:40'),(Weekly '18:40'),(Weekly '20:40'))
 cleanup=@((Weekly '09:35'),(Weekly '20:45'))
}
if (-not $Apply) { Write-Host 'PREVIEW ONLY. No tasks changed.'; return }
$backup = Join-Path $root ('logs\reliability-task-backup-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $backup -Force | Out-Null
foreach ($name in $names.Keys) {
    Export-ScheduledTask -TaskName $name -TaskPath '\' | Set-Content -Path (Join-Path $backup ($names[$name]+'.xml')) -Encoding Unicode
}
Write-Host "Original task definitions: $backup"
$changed = @()
try {
    foreach ($name in $names.Keys) {
        $kind=$names[$name]
        $t=Get-ScheduledTask -TaskName $name -TaskPath '\'
        if ($t.State -eq 'Running') { throw "Task became active: $name" }
        $action=New-ScheduledTaskAction -Execute 'powershell.exe' -Argument ('-NoProfile -ExecutionPolicy Bypass -File "'+(Join-Path $root 'run_model2_reliability.ps1')+'" -Task '+$kind) -WorkingDirectory $root
        $params=@{TaskName=$name;TaskPath='\';Action=$action;ErrorAction='Stop'}
        if ($triggers.ContainsKey($kind)) { $params.Trigger=$triggers[$kind] }
        if ($kind -eq 'cleanup') {
            $settings=$t.Settings
            $settings.DisallowStartIfOnBatteries=$false
            $settings.StopIfGoingOnBatteries=$false
            $params.Settings=$settings
        }
        $changed += $name
        Set-ScheduledTask @params | Out-Null
        Write-Host "Updated $name"
    }
} catch {
    Write-Warning "Installation stopped: $_. Attempting rollback of modified tasks."
    foreach ($name in $changed) {
        try {
            $original=$old[$name]
            Set-ScheduledTask -TaskName $name -TaskPath '\' -Action $original.Actions -Trigger $original.Triggers -Settings $original.Settings | Out-Null
        } catch { Write-Warning "Rollback failed for $name; use backup: $backup" }
    }
    throw
}
Write-Host 'Done. No tasks explicitly started. Verify task settings and next-run times.'
