# Sarthak AI — Binary installer (Windows PowerShell)
#
# Downloads the correct pre-built .exe from GitHub Releases,
# verifies its SHA-256 checksum, and installs to %LOCALAPPDATA%\sarthak\bin\.
#
# Usage (PowerShell):
#   irm https://raw.githubusercontent.com/productive-pro/sarthak/main/scripts/install-binary.ps1 | iex
#
# Install a specific version:
#   $env:SARTHAK_VERSION="v1.2.3"
#   irm https://... | iex
#
# Install to a custom directory:
#   $env:SARTHAK_BIN_DIR="C:\tools"
#   irm https://... | iex

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Repo        = "productive-pro/sarthak"
$ApiUrl      = "https://api.github.com/repos/$Repo/releases"
$ReleasesUrl = "https://github.com/$Repo/releases"
$AssetName   = "sarthak-windows-x86_64.exe"

$Version    = $env:SARTHAK_VERSION
$BinDir     = if ($env:SARTHAK_BIN_DIR) { $env:SARTHAK_BIN_DIR } `
              else { Join-Path $env:LOCALAPPDATA "sarthak\bin" }
$NoVerify   = $env:SARTHAK_NO_VERIFY -eq "1"

function Write-Ok($msg)   { Write-Host "  [+] $msg" -ForegroundColor Green }
function Write-Info($msg) { Write-Host "  [>] $msg" -ForegroundColor Cyan }
function Write-Warn($msg) { Write-Host "  [!] $msg" -ForegroundColor Yellow }
function Write-Fail($msg) { Write-Host "  [x] $msg" -ForegroundColor Red; exit 1 }

Write-Host ""
Write-Host "  Sarthak AI Installer" -ForegroundColor White
Write-Host ""

Write-Info "Platform : windows/x86_64"
Write-Info "Binary   : $AssetName"
Write-Info "Install  : $BinDir\sarthak.exe"

# ── Resolve version ───────────────────────────────────────────────────────────
if (-not $Version) {
    Write-Info "Fetching latest release …"
    try {
        $latest = Invoke-RestMethod "$ApiUrl/latest" -Headers @{ "User-Agent" = "sarthak-installer" }
        $Version = $latest.tag_name
    } catch {
        Write-Fail "Could not fetch latest release. Set `$env:SARTHAK_VERSION=vX.Y.Z"
    }
}
Write-Ok "Version  : $Version"

$BaseUrl   = "$ReleasesUrl/download/$Version"
$BinaryUrl = "$BaseUrl/$AssetName"
$SumsUrl   = "$BaseUrl/SHA256SUMS.txt"

# ── Download to temp dir ──────────────────────────────────────────────────────
$Tmp       = Join-Path $env:TEMP ("sarthak_install_" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $Tmp | Out-Null

$BinaryTmp = Join-Path $Tmp $AssetName
$SumsTmp   = Join-Path $Tmp "SHA256SUMS.txt"

Write-Info "Downloading binary …"
try {
    Invoke-WebRequest $BinaryUrl -OutFile $BinaryTmp -UseBasicParsing
} catch {
    Write-Fail "Download failed: $BinaryUrl`n  $_"
}
$sizeMB = [math]::Round((Get-Item $BinaryTmp).Length / 1MB, 1)
Write-Ok "Downloaded ${sizeMB} MB"

# ── Verify SHA-256 ────────────────────────────────────────────────────────────
if ($NoVerify) {
    Write-Warn "Checksum verification skipped"
} else {
    Write-Info "Verifying SHA-256 checksum …"
    try {
        Invoke-WebRequest $SumsUrl -OutFile $SumsTmp -UseBasicParsing
        $content  = Get-Content $SumsTmp
        $line     = $content | Where-Object { $_ -match [regex]::Escape($AssetName) } | Select-Object -First 1
        if ($line) {
            $expected = ($line -split '\s+')[0].ToLower()
            $actual   = (Get-FileHash $BinaryTmp -Algorithm SHA256).Hash.ToLower()
            if ($actual -ne $expected) {
                Write-Fail "Checksum mismatch!`n  Expected : $expected`n  Got      : $actual`n  Download may be corrupted."
            }
            Write-Ok "Checksum verified"
        } else {
            Write-Warn "Checksum for $AssetName not in SHA256SUMS.txt — skipping"
        }
    } catch {
        Write-Warn "Could not fetch SHA256SUMS.txt — skipping verification"
    }
}

# ── Install ───────────────────────────────────────────────────────────────────
New-Item -ItemType Directory -Force -Path $BinDir | Out-Null
$Dest = Join-Path $BinDir "sarthak.exe"
Copy-Item $BinaryTmp $Dest -Force
Write-Ok "Installed → $Dest"

# ── Add to user PATH ──────────────────────────────────────────────────────────
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($userPath -notlike "*$BinDir*") {
    [Environment]::SetEnvironmentVariable("Path", "$userPath;$BinDir", "User")
    Write-Ok "Added $BinDir to user PATH (restart terminal to take effect)"
} else {
    Write-Ok "$BinDir already in PATH"
}

# ── Cleanup ───────────────────────────────────────────────────────────────────
Remove-Item -Recurse -Force $Tmp

# ── Done ─────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "  Done!" -ForegroundColor Green
Write-Info "Run  sarthak configure  to choose your AI provider."
Write-Info "Run  sarthak --help     to see all commands."
Write-Host ""
