# Register a logon Task Scheduler job that keeps the IPTV monitor running.
# Overview: Windows-only. Do NOT enable this while the OVH VPS systemd unit is live —
# two monitors will fight over EPGenius swaps.
# Run from the repo:
#   powershell -ExecutionPolicy Bypass -File scripts\install-windows-task.ps1

$ErrorActionPreference = "Stop"

$taskName = "IPTVPortalMonitor"
$repoRoot = Split-Path -Parent $PSScriptRoot
$pythonw = Join-Path $repoRoot ".venv\Scripts\pythonw.exe"
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
$exe = if (Test-Path $pythonw) { $pythonw } else { $python }

if (-not (Test-Path $exe)) {
    throw "Virtualenv not found at $exe. Create .venv first."
}

Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue | Unregister-ScheduledTask -Confirm:$false

$action = New-ScheduledTaskAction -Execute $exe -Argument "main.py" -WorkingDirectory $repoRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -DontStopOnIdleEnd `
    -StartWhenAvailable `
    -RestartCount 5 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit ([TimeSpan]::Zero)
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Health-check IPTV portal URLs and fail over via EPGenius. Dashboard at http://127.0.0.1:8787" `
    | Out-Null

Start-ScheduledTask -TaskName $taskName

Write-Host "Registered and started scheduled task '$taskName'."
Write-Host "Dashboard: http://127.0.0.1:8787"
Write-Host "Logs: $repoRoot\logs\monitor.log"
Write-Host "Stop: powershell -ExecutionPolicy Bypass -File `"$PSScriptRoot\uninstall-windows-task.ps1`""
