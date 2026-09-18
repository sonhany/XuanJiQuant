param(
    [string]$TaskName = "XuanJiQuant-Paper-Intraday"
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
    -Argument ("-NoLogo -NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$launcher`" -TaskKey paper_intraday") `
    -WorkingDirectory $projectRoot

$windows = @(
    @{ Start = "09:35"; End = "11:25" },
    @{ Start = "13:05"; End = "14:50" }
)
$triggers = @()
foreach ($window in $windows) {
    $current = [datetime]::ParseExact($window.Start, "HH:mm", $null)
    $end = [datetime]::ParseExact($window.End, "HH:mm", $null)
    while ($current -le $end) {
        $triggers += New-ScheduledTaskTrigger `
            -Weekly `
            -WeeksInterval 1 `
            -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday `
            -At $current.ToString("HH:mm")
        $current = $current.AddMinutes(5)
    }
}

$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 4) `
    -StartWhenAvailable

$currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal -UserId $currentUser -LogonType Interactive -RunLevel Limited
$task = New-ScheduledTask -Action $action -Trigger $triggers -Settings $settings -Principal $principal `
    -Description "F5 current-time intraday paper simulation; no broker authority"

Register-ScheduledTask -TaskName $TaskName -InputObject $task -Force | Out-Null
Write-Output "Installed $TaskName at 09:35 Monday-Friday, every 5 minutes for 5h20m (IgnoreNew)."
