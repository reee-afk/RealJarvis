<#
Stops and removes the JARVIS scheduled task. Run:
    powershell -ExecutionPolicy Bypass -File .\scripts\uninstall-windows-task.ps1
#>

$taskName = "JARVIS"

$task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if (-not $task) {
    Write-Host "No '$taskName' scheduled task found — nothing to remove."
    exit 0
}

Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false

Write-Host "JARVIS scheduled task removed. It will no longer start at logon."
Write-Host "If a copy is running right now, it's been stopped too."
