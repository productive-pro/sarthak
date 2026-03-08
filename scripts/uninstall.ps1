# Sarthak AI — Uninstall (Windows PowerShell)
# Removes the Task Scheduler job, binary, and ~/.sarthak_ai directory.

$ErrorActionPreference = "SilentlyContinue"

$InstallDir = Join-Path $HOME ".sarthak_ai"
$BinDir     = if ($env:SARTHAK_BIN_DIR) { $env:SARTHAK_BIN_DIR } `
              else { Join-Path $env:LOCALAPPDATA "sarthak\bin" }
$SarthakExe = Join-Path $BinDir "sarthak.exe"
$TaskName   = "SarthakOrchestrator"

function Write-Ok($m)   { Write-Host "  [+] $m" -ForegroundColor Green }
function Write-Warn($m) { Write-Host "  [!] $m" -ForegroundColor Yellow }

Write-Host "`n  :: Sarthak AI -- Uninstall" -ForegroundColor Yellow

# Stop and remove Task Scheduler job
$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($task) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Ok "Scheduled task '$TaskName' removed"
} else {
    Write-Warn "Scheduled task '$TaskName' not found (already removed?)"
}

# Remove binary
if (Test-Path $SarthakExe) {
    Remove-Item $SarthakExe -Force -ErrorAction SilentlyContinue
    Write-Ok "Removed $SarthakExe"
} else {
    Write-Warn "$SarthakExe not found (already removed?)"
}

# Remove wrapper bat
$WrapperBat = Join-Path $InstallDir "run_orchestrator.bat"
if (Test-Path $WrapperBat) {
    Remove-Item $WrapperBat -Force -ErrorAction SilentlyContinue
    Write-Ok "Removed wrapper script"
}

# Try uv tool uninstall
$uv = Get-Command uv -ErrorAction SilentlyContinue
if ($uv) {
    try { & $uv.Source tool uninstall sarthak 2>$null; Write-Ok "uv tool uninstalled sarthak" } catch {}
}

# Remove bin directory if empty
if ((Test-Path $BinDir) -and (Get-ChildItem $BinDir -ErrorAction SilentlyContinue).Count -eq 0) {
    Remove-Item $BinDir -Force -ErrorAction SilentlyContinue
}

# Remove config and data directory
if (Test-Path $InstallDir) {
    Remove-Item $InstallDir -Recurse -Force -ErrorAction SilentlyContinue
    Write-Ok "Removed $InstallDir"
} else {
    Write-Warn "$InstallDir not found (already removed?)"
}

Write-Host "`n  [+] Sarthak AI uninstalled." -ForegroundColor Green
Write-Host ""
