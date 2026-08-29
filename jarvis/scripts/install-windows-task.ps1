<#
Registers JARVIS as a Windows Scheduled Task: starts at logon, restarts
itself automatically if it ever dies, no console window, no admin rights
needed. Uses Task Scheduler (built into Windows) rather than a third-party
service manager, keeping the "no extra installs" promise.

Run from PowerShell:
    powershell -ExecutionPolicy Bypass -File .\scripts\install-windows-task.ps1
#>

$ErrorActionPreference = "Stop"

$jarvisDir = Split-Path -Parent $PSScriptRoot
$launcher = Join-Path $jarvisDir "scripts\run_hidden.pyw"
$envFile = Join-Path $jarvisDir ".env"
$taskName = "JARVIS"

if (-not (Test-Path $envFile)) {
    Write-Host "No .env found at $envFile" -ForegroundColor Yellow
    Write-Host "Copy .env.example to .env and fill in ELEVENLABS_API_KEY first, then re-run this script."
    exit 1
}

# --- find a windowless Python launcher ---
$exe = $null
$cmd = Get-Command pythonw.exe -ErrorAction SilentlyContinue
if ($cmd) { $exe = $cmd.Source }

if (-not $exe) {
    $py = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($py) {
        $candidate = Join-Path (Split-Path $py.Source) "pythonw.exe"
        if (Test-Path $candidate) { $exe = $candidate }
    }
}

if (-not $exe) {
    $pyw = Get-Command pyw.exe -ErrorAction SilentlyContinue
    if ($pyw) { $exe = $pyw.Source }
}

if (-not $exe) {
    Write-Host "Couldn't find pythonw.exe or pyw.exe on PATH. Install Python from python.org with 'Add python.exe to PATH' checked, then re-run this script." -ForegroundColor Red
    exit 1
}

Write-Host "Using: $exe"
Write-Host "Working directory: $jarvisDir"

$action = New-ScheduledTaskAction -Execute $exe -Argument "`"$launcher`"" -WorkingDirectory $jarvisDir
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal `
    -Description "JARVIS voice assistant — starts at logon, restarts automatically if it dies." `
    -Force | Out-Null

Start-ScheduledTask -TaskName $taskName

Write-Host ""
Write-Host "JARVIS is installed and starting now." -ForegroundColor Cyan
Write-Host "It will start automatically every time you log in, from here on."
Write-Host ""
Write-Host "Check it's up:   http://localhost:8420  (give it a few seconds)"
Write-Host "Logs:            $jarvisDir\jarvis.log"
Write-Host "Task status:     Get-ScheduledTaskInfo -TaskName $taskName"
Write-Host "Stop it now:     Stop-ScheduledTask -TaskName $taskName"
Write-Host "Remove entirely: .\scripts\uninstall-windows-task.ps1"
