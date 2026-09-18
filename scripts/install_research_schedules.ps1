param()

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = (Get-Command python -ErrorAction Stop).Source
$qlibPython = Join-Path $projectRoot ".venv-qlib\Scripts\python.exe"
$launcher = Join-Path $projectRoot "scripts\run_hidden_scheduled_task.ps1"
$powershellPath = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"

if (-not (Test-Path -LiteralPath $python)) {
    throw "Project Python not found: $python"
}
if (-not (Test-Path -LiteralPath $qlibPython)) {
    throw "Qlib isolated Python not found: $qlibPython"
}
if (-not (Test-Path -LiteralPath $launcher -PathType Leaf)) {
    throw "Hidden task launcher not found: $launcher"
}

function Register-XuanJiTask {
    param(
        [Parameter(Mandatory = $true)][string]$TaskName,
        [Parameter(Mandatory = $true)][string]$TaskKey,
        [Parameter(Mandatory = $true)]$Trigger,
        [Parameter(Mandatory = $true)][int]$RestartCount,
        [Parameter(Mandatory = $true)][int]$RestartMinutes,
        [Parameter(Mandatory = $true)][int]$ExecutionHours,
        [Parameter(Mandatory = $true)][string]$Description
    )

    $action = New-ScheduledTaskAction `
        -Execute $powershellPath `
        -Argument ("-NoLogo -NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$launcher`" -TaskKey $TaskKey") `
        -WorkingDirectory $projectRoot
    $settings = New-ScheduledTaskSettingsSet `
        -StartWhenAvailable `
        -ExecutionTimeLimit (New-TimeSpan -Hours $ExecutionHours) `
        -RestartCount $RestartCount `
        -RestartInterval (New-TimeSpan -Minutes $RestartMinutes) `
        -MultipleInstances IgnoreNew `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries
    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $action `
        -Trigger $Trigger `
        -Settings $settings `
        -Description $Description `
        -Force | Out-Null
}

# Contract labels retained for source-level schedule auditing:
# MON,TUE,WED,THU,FRI 16:20 primary
# MON,TUE,WED,THU,FRI 20:30 idempotent recovery
# SAT 18:30
# SUN 10:00
$dailyPrimaryTrigger = New-ScheduledTaskTrigger `
    -Weekly `
    -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday `
    -At "16:20"
$dailyRecoveryTrigger = New-ScheduledTaskTrigger `
    -Weekly `
    -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday `
    -At "20:30"
$dailyTriggers = @($dailyPrimaryTrigger, $dailyRecoveryTrigger)
Register-XuanJiTask `
    -TaskName "XuanJiQuant-Research-Daily" `
    -TaskKey "research_daily" `
    -Trigger $dailyTriggers `
    -RestartCount 3 `
    -RestartMinutes 15 `
    -ExecutionHours 4 `
    -Description "XuanJiQuant daily data, factor and research selection pipeline (research only)"

$qlibTrigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Saturday -At "18:30"
Register-XuanJiTask `
    -TaskName "XuanJiQuant-Qlib-Weekly" `
    -TaskKey "qlib_weekly" `
    -Trigger $qlibTrigger `
    -RestartCount 2 `
    -RestartMinutes 30 `
    -ExecutionHours 4 `
    -Description "XuanJiQuant six-year PIT, industry and benchmark weekly update (research only)"

$strategyTrigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At "10:00"
Register-XuanJiTask `
    -TaskName "XuanJiQuant-Strategy-Weekly" `
    -TaskKey "strategy_weekly" `
    -Trigger $strategyTrigger `
    -RestartCount 2 `
    -RestartMinutes 30 `
    -ExecutionHours 12 `
    -Description "XuanJiQuant F4 strategy and portfolio validation (research only)"

Write-Host "Installed XuanJiQuant deterministic research schedules."
