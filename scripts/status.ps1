$ErrorActionPreference = "SilentlyContinue"

# Check PATH first
$cmd = Get-Command sarthak -ErrorAction SilentlyContinue
if ($cmd) {
    & $cmd.Source status
    exit
}

# Fallback: check the default binary install location
$BinDir = if ($env:SARTHAK_BIN_DIR) { $env:SARTHAK_BIN_DIR } `
          else { Join-Path $env:LOCALAPPDATA "sarthak\bin" }
$exe = Join-Path $BinDir "sarthak.exe"
if (Test-Path $exe) {
    & $exe status
    exit
}

Write-Host "sarthak not found in PATH or $BinDir." -ForegroundColor Yellow
exit 1
