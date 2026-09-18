param(
    [string]$TaskName = "XuanJiQuant-Qlib-Weekly",
    [string]$StartTime = "18:30"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".venv-qlib\Scripts\python.exe"
$launcher = Join-Path $projectRoot "scripts\run_hidden_scheduled_task.ps1"
$powershellPath = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
if (-not (Test-Path -LiteralPath $python)) {
    throw "Qlib isolated Python not found: $python"
}
if (-not (Test-Path -LiteralPath $launcher -PathType Leaf)) {
    throw "Hidden task launcher not found: $launcher"
}

$action = New-ScheduledTaskAction `
    -Execute $powershellPath `
    -Argument ("-NoLogo -NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$launcher`" -TaskKey qlib_weekly") `
    -WorkingDirectory $projectRoot
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Saturday -At $StartTime # SAT 18:30
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 4) `
    -RestartCount 2 `
    -RestartInterval (New-TimeSpan -Minutes 30) `
    -MultipleInstances IgnoreNew
Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "XuanJiQuant six-year PIT, industry and benchmark weekly update (research only)" `
    -Force | Out-Null
Write-Host "Installed task '$TaskName' for Saturday $StartTime."
