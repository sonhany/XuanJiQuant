param(
    [string]$TaskName = "XuanJiQuant-Service"
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$manager = Join-Path $projectRoot "scripts\service_manager.py"
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name

if (-not (Test-Path -LiteralPath $manager -PathType Leaf)) {
    throw "Service manager not found: $manager"
}
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    $python = "python"
}

$trigger = New-ScheduledTaskTrigger -AtLogOn -User $currentUser
$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId $currentUser -LogonType Interactive -RunLevel Limited

$action = New-ScheduledTaskAction `
    -Execute $python `
    -Argument "`"$manager`"" `
    -WorkingDirectory $projectRoot

$task = New-ScheduledTask `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "XuanJiQuant unified service manager (API + Web + Supervisor); no trading authority"

Register-ScheduledTask -TaskName $TaskName -InputObject $task -Force | Out-Null

# Unregister legacy tasks if they exist
foreach ($legacy in @("XuanJiQuant-API-Service", "XuanJiQuant-Web-Service", "XuanJiQuant-Service-Supervisor")) {
    $existing = Get-ScheduledTask -TaskName $legacy -ErrorAction SilentlyContinue
    if ($existing) {
        Unregister-ScheduledTask -TaskName $legacy -Confirm:$false
        Write-Output "  Unregistered legacy task: $legacy"
    }
}

Write-Output "Installed $TaskName (hidden, task-owned, no trading authority)."
