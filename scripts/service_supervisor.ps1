param(
    [string]$TaskName = "XuanJiQuant-Service"
)

$ErrorActionPreference = "Stop"
$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
if ($task.State -ne "Running") {
    Start-ScheduledTask -TaskName $TaskName
}
