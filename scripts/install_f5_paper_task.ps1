param(
    [string]$TaskName = "XuanJiQuant-Paper-Daily"
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$launcher = Join-Path $projectRoot "scripts\run_hidden_scheduled_task.ps1"
$powershellPath = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"

if (-not (Test-Path -LiteralPath $launcher -PathType Leaf)) {
    throw "Hidden task launcher not found: $launcher"
}

$action = New-ScheduledTaskAction `
    -Execute $powershellPath `
    -Argument ("-NoLogo -NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$launcher`" -TaskKey paper_daily") `
    -WorkingDirectory $projectRoot

$trigger = New-ScheduledTaskTrigger `
    -Weekly `
    -WeeksInterval 1 `
    -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday `
    -At "17:10"

$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -RestartInterval (New-TimeSpan -Minutes 15) `
    -RestartCount 3 `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -StartWhenAvailable

$currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal -UserId $currentUser -LogonType Interactive -RunLevel Limited
$task = New-ScheduledTask -Action $action -Trigger $trigger -Settings $settings -Principal $principal `
    -Description "F5 deterministic daily paper execution; simulation only; no broker authority"

Register-ScheduledTask -TaskName $TaskName -InputObject $task -Force | Out-Null
Write-Output "Installed $TaskName at 17:10 Monday-Friday (IgnoreNew, retry 15m x3, limit 2h)."
