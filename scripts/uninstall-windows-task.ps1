# Stop and remove the IPTV monitor scheduled task (Windows).
# Overview: use this after moving the live monitor to the VPS.
#   powershell -ExecutionPolicy Bypass -File scripts\uninstall-windows-task.ps1

$ErrorActionPreference = "Stop"
$taskName = "IPTVPortalMonitor"

$task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if (-not $task) {
    Write-Host "Task '$taskName' is not installed."
    exit 0
}

if ($task.State -eq "Running") {
    Stop-ScheduledTask -TaskName $taskName
}

Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
Write-Host "Removed scheduled task '$taskName'."
