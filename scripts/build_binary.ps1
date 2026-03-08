# Sarthak AI — Build standalone binary (Windows)
#
# Uses PyInstaller to produce a single .exe that includes all deps + data files.
#
# Usage:
#   .\scripts\build_binary.ps1
#   $env:ASSET_NAME="sarthak-windows-x86_64.exe"; .\scripts\build_binary.ps1

$ErrorActionPreference = "Stop"

$RepoRoot  = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$DistDir   = Join-Path $RepoRoot "dist"
$BuildDir  = Join-Path $RepoRoot "build"
$AssetName = if ($env:ASSET_NAME) { $env:ASSET_NAME } else { "sarthak.exe" }

Set-Location $RepoRoot
New-Item -ItemType Directory -Force -Path $DistDir  | Out-Null
New-Item -ItemType Directory -Force -Path $BuildDir | Out-Null

Write-Host "  > Building Sarthak binary: $AssetName"

# ── Data files ────────────────────────────────────────────────────────────────
$sep = ";"   # Windows separator for --add-data
$AddData = @(
    "src\sarthak\data\providers.json${sep}sarthak/data",
    "src\sarthak\data\config.toml${sep}sarthak/data",
    "src\sarthak\core\ai_utils\prompts.json${sep}sarthak/core/ai_utils"
)

# ── Hidden imports ────────────────────────────────────────────────────────────
$Hidden = @(
    "sarthak.cli",
    "sarthak.cli.spaces_cli",
    "sarthak.cli.agents_cli",
    "sarthak.cli.analytics_cli",
    "sarthak.core.setup",
    "sarthak.core.configure",
    "sarthak.core.config",
    "sarthak.core.ai_utils.catalog",
    "sarthak.core.ai_utils.multi_provider",
    "sarthak.core.ai_utils.provider_registry",
    "sarthak.storage.encrypt",
    "tomlkit",
    "questionary",
    "structlog",
    "aiosqlite",
    "pydantic_ai",
    "cryptography",
    "httpx",
    "win32api",
    "win32con"
)

$Args = @(
    "--onefile",
    "--name", "sarthak",
    "--distpath", $DistDir,
    "--workpath", (Join-Path $BuildDir "pyinstaller_work"),
    "--specpath", $BuildDir,
    "--noconfirm",
    "--clean",
    "--collect-all", "sarthak",
    "--collect-all", "pydantic_ai",
    "--collect-data", "textual",
    "--collect-data", "rich"
)

foreach ($d in $AddData)  { $Args += "--add-data"; $Args += $d }
foreach ($h in $Hidden)   { $Args += "--hidden-import"; $Args += $h }

$Args += "src\sarthak\cli\__main__.py"

pyinstaller @Args

# ── Rename to ASSET_NAME ──────────────────────────────────────────────────────
$Built = Join-Path $DistDir "sarthak.exe"
$Final = Join-Path $DistDir $AssetName
if (($AssetName -ne "sarthak.exe") -and (Test-Path $Built)) {
    Move-Item $Built $Final -Force
}

Write-Host ""
Write-Host "  + Binary: $Final"
Get-Item $Final | Select-Object Name, @{n="Size";e={ "$([math]::Round($_.Length/1MB,1)) MB" }}
