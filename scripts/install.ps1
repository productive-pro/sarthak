# Sarthak AI — Full installer (Windows PowerShell)
#
# Installation modes:
#   $env:BINARY_INSTALL="1"     — download pre-built .exe from GitHub Releases
#   $env:RELEASE_TAG="vX.Y.Z"   — install that exact version from PyPI via uv tool install
#   (default)                   — install latest from PyPI via uv tool install
#
# Other variables:
#   $env:SARTHAK_VERSION   — alias for RELEASE_TAG (binary + PyPI)
#   $env:SKIP_WIZARD       — "true" to skip configure wizard
#   $env:SARTHAK_BIN_DIR   — override binary install directory
#   $env:SARTHAK_NO_VERIFY — "1" to skip SHA-256 verification

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Repo        = "productive-pro/sarthak"
$RepoUrl     = "https://github.com/$Repo"
$ApiUrl      = "https://api.github.com/repos/$Repo/releases"
$AssetName   = "sarthak-windows-x86_64.exe"

$ReleaseTag    = $env:RELEASE_TAG
$Version       = if ($env:SARTHAK_VERSION) { $env:SARTHAK_VERSION } else { $ReleaseTag }
$InstallDir    = Join-Path $HOME ".sarthak_ai"
$ConfigFile    = Join-Path $InstallDir "config.toml"
$LogsDir       = Join-Path $InstallDir "logs"
$BinDir        = if ($env:SARTHAK_BIN_DIR) { $env:SARTHAK_BIN_DIR } `
                 else { Join-Path $env:LOCALAPPDATA "sarthak\bin" }
$NoVerify      = $env:SARTHAK_NO_VERIFY -eq "1"
$BinaryInstall = $env:BINARY_INSTALL -eq "1"
$SkipWizard    = $env:SKIP_WIZARD -eq "true"
$TaskName      = "SarthakOrchestrator"

function Write-Ok($m)   { Write-Host "  [+] $m" -ForegroundColor Green }
function Write-Info($m) { Write-Host "  [>] $m" -ForegroundColor Cyan }
function Write-Warn($m) { Write-Host "  [!] $m" -ForegroundColor Yellow }
function Write-Fail($m) { Write-Host "  [x] $m" -ForegroundColor Red; exit 1 }
function Write-Hdr($m)  { Write-Host "`n  :: $m" -ForegroundColor Yellow }
function Write-Step($n, $t, $total) { Write-Host "`n  [$n/$total] $t" -ForegroundColor Cyan }

Write-Hdr "Sarthak AI Installer"
Write-Info "Platform : windows/x86_64"

New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
New-Item -ItemType Directory -Force -Path $BinDir     | Out-Null
New-Item -ItemType Directory -Force -Path $LogsDir    | Out-Null

# Ensure uv bin dirs are in PATH for this session
$uvBin    = Join-Path $env:USERPROFILE ".local\bin"
$cargoBin = Join-Path $env:USERPROFILE ".cargo\bin"
$env:Path = "$uvBin;$cargoBin;$BinDir;$env:Path"

$TotalSteps = 5

# Helper: ensure uv is available
function Ensure-Uv {
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        Write-Info "uv not found — installing ..."
        Invoke-RestMethod "https://astral.sh/uv/install.ps1" | Invoke-Expression
        $env:Path = "$uvBin;$cargoBin;$env:Path"
        if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
            Write-Fail "uv install failed. Install manually from https://github.com/astral-sh/uv"
        }
        Write-Ok "uv installed"
    }
}


# —————————————————————————————————————————————————————————————————————————————
# Step 1: Install the sarthak executable
# —————————————————————————————————————————————————————————————————————————————
Write-Step 1 "Installing sarthak" $TotalSteps

if ($BinaryInstall) {
    # ── Binary from GitHub Releases ──────────────────────────────────────────
    if (-not $Version) {
        Write-Info "Fetching latest release ..."
        try {
            $latest  = Invoke-RestMethod "$ApiUrl/latest" -Headers @{"User-Agent"="sarthak-installer"}
            $Version = $latest.tag_name
        } catch { Write-Fail "Could not fetch latest release. Set `$env:SARTHAK_VERSION=vX.Y.Z" }
    }
    Write-Info "Version : $Version"

    $BaseUrl   = "$RepoUrl/releases/download/$Version"
    $BinaryUrl = "$BaseUrl/$AssetName"
    $SumsUrl   = "$BaseUrl/SHA256SUMS.txt"
    $Tmp       = Join-Path $env:TEMP ("sarthak_install_" + [Guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $Tmp | Out-Null

    Write-Info "Downloading $AssetName ..."
    $BinaryTmp = Join-Path $Tmp $AssetName
    try { Invoke-WebRequest $BinaryUrl -OutFile $BinaryTmp -UseBasicParsing }
    catch { Write-Fail "Download failed: $BinaryUrl`n  $_" }

    Write-Ok "Downloaded $([math]::Round((Get-Item $BinaryTmp).Length / 1MB, 1)) MB"

    if (-not $NoVerify) {
        try {
            $SumsTmp = Join-Path $Tmp "SHA256SUMS.txt"
            Invoke-WebRequest $SumsUrl -OutFile $SumsTmp -UseBasicParsing
            $line = (Get-Content $SumsTmp) | Where-Object { $_ -match [regex]::Escape($AssetName) } | Select-Object -First 1
            if ($line) {
                $expected = ($line -split '\s+')[0].ToLower()
                $actual   = (Get-FileHash $BinaryTmp -Algorithm SHA256).Hash.ToLower()
                if ($actual -ne $expected) { Write-Fail "Checksum mismatch!`n  Expected: $expected`n  Got     : $actual" }
                Write-Ok "Checksum verified"
            }
        } catch { Write-Warn "Could not verify checksum — skipping" }
    }

    $SarthakExe = Join-Path $BinDir "sarthak.exe"
    Copy-Item $BinaryTmp $SarthakExe -Force
    Remove-Item -Recurse -Force $Tmp
    Write-Ok "Binary installed: $SarthakExe"

} elseif ($ReleaseTag) {
    # ── Specific version from PyPI ────────────────────────────────────────────
    Ensure-Uv
    $ver = $ReleaseTag.TrimStart("v")
    Write-Info "Installing sarthak==$ver from PyPI ..."
    uv tool install "sarthak[cloud]==$ver" --force
    # uv installs to ~/.local/bin on Windows (uv ≥0.4) or %APPDATA%\uv\bin (older)
    $cmd = Get-Command sarthak -ErrorAction SilentlyContinue
    if ($cmd) {
        $SarthakExe = $cmd.Source
    } else {
        $uvLocalBin = Join-Path $HOME ".local\bin\sarthak.exe"
        $uvAppBin   = Join-Path $env:APPDATA "uv\bin\sarthak.exe"
        $SarthakExe = if (Test-Path $uvLocalBin) { $uvLocalBin } `
                      elseif (Test-Path $uvAppBin) { $uvAppBin } `
                      else { Join-Path $BinDir "sarthak.exe" }
    }
    Write-Ok "Installed sarthak==$ver : $SarthakExe"

} else {
    # ── Latest from PyPI (default) ────────────────────────────────────────────
    Ensure-Uv
    Write-Info "Installing latest sarthak from PyPI ..."
    uv tool install "sarthak[cloud]" --upgrade
    $cmd = Get-Command sarthak -ErrorAction SilentlyContinue
    if ($cmd) {
        $SarthakExe = $cmd.Source
    } else {
        $uvLocalBin = Join-Path $HOME ".local\bin\sarthak.exe"
        $uvAppBin   = Join-Path $env:APPDATA "uv\bin\sarthak.exe"
        $SarthakExe = if (Test-Path $uvLocalBin) { $uvLocalBin } `
                      elseif (Test-Path $uvAppBin) { $uvAppBin } `
                      else { Join-Path $BinDir "sarthak.exe" }
    }
    Write-Ok "Installed latest sarthak : $SarthakExe"
}

if (-not (Test-Path $SarthakExe)) { Write-Fail "sarthak executable not found at $SarthakExe" }

# Add dirs to user PATH if not already present
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
foreach ($dir in @($BinDir, $uvBin)) {
    if ($userPath -notlike "*$dir*") {
        $userPath = "$userPath;$dir"
        [Environment]::SetEnvironmentVariable("Path", $userPath, "User")
        $env:Path += ";$dir"
        Write-Ok "Added $dir to user PATH"
    }
}


# —————————————————————————————————————————————————————————————————————————————
# Step 2: First-run bootstrap
# —————————————————————————————————————————————————————————————————————————————
Write-Step 2 "Setting up ~/.sarthak_ai" $TotalSteps
try { & $SarthakExe status 2>$null | Out-Null } catch {}
Write-Ok "~/.sarthak_ai ready"

# —————————————————————————————————————————————————————————————————————————————
# Step 3: Interactive configuration wizard
# —————————————————————————————————————————————————————————————————————————————
Write-Step 3 "Configuring Sarthak AI" $TotalSteps
if ($SkipWizard) {
    Write-Warn "Wizard skipped — run 'sarthak configure' later"
} else {
    Write-Info "Launching configuration wizard …"
    try { & $SarthakExe configure --mode full }
    catch { Write-Warn "Wizard exited early — run 'sarthak configure' later" }
}

# —————————————————————————————————————————————————————————————————————————————
# Step 4: Install orchestrator service (Task Scheduler)
# —————————————————————————————————————————————————————————————————————————————
Write-Step 4 "Installing orchestrator (Task Scheduler)" $TotalSteps

# Delegate to the CLI so install.ps1 and `sarthak service install` share one code path
try {
    & $SarthakExe service install
    Write-Ok "Orchestrator service installed"
} catch {
    Write-Warn "CLI service install failed — attempting direct fallback"
    # Task Scheduler doesn't support per-task env vars, so we use a wrapper .bat
    $WrapperBat = Join-Path $InstallDir "run_orchestrator.bat"
    $WrapperContent = "@echo off`r`nset SARTHAK_CONFIG=$ConfigFile`r`nset SARTHAK_ORCHESTRATOR_SKIP_CAPTURE=1`r`n`"$SarthakExe`" orchestrator`r`n"
    [System.IO.File]::WriteAllText($WrapperBat, $WrapperContent, [System.Text.Encoding]::ASCII)

    $Action    = New-ScheduledTaskAction -Execute $WrapperBat -WorkingDirectory $InstallDir
    $Trigger   = New-ScheduledTaskTrigger -AtLogOn
    $Settings  = New-ScheduledTaskSettingsSet `
        -RestartCount 5 `
        -RestartInterval (New-TimeSpan -Minutes 1) `
        -ExecutionTimeLimit ([TimeSpan]::Zero) `
        -StartWhenAvailable
    $Principal = New-ScheduledTaskPrincipal -LogonType Interactive -RunLevel Limited

    try { Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue } catch {}
    Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger `
        -Settings $Settings -Principal $Principal -Force | Out-Null
    try { Start-ScheduledTask -TaskName $TaskName } catch { Write-Warn "Task start deferred — it will run at next login" }
    Write-Ok "Scheduled task '$TaskName' registered (fallback)"
}

# —————————————————————————————————————————————————————————————————————————————
# Step 5: Summary
# —————————————————————————————————————————————————————————————————————————————
Write-Step 5 "Done" $TotalSteps

Write-Hdr "Installation complete"
Write-Info "Config & data : $InstallDir"
Write-Info "Executable    : $SarthakExe"
Write-Info "Service       : Task Scheduler → $TaskName"

$webHost = "localhost"; $webPort = 4848
if (Test-Path $ConfigFile) {
    $cfgLines = Get-Content $ConfigFile
    $hLine = $cfgLines | Where-Object { $_ -match '^\s*host\s*=' } | Select-Object -First 1
    $pLine = $cfgLines | Where-Object { $_ -match '^\s*port\s*=' } | Select-Object -First 1
    if ($hLine) { $webHost = ($hLine -split '=',2)[1].Trim().Trim('"') }
    if ($pLine) { $webPort = ($pLine -split '=',2)[1].Trim() }
    if ($webHost -in @("127.0.0.1","0.0.0.0")) { $webHost = "localhost" }
}

Write-Host ""
Write-Host "  ✓  Sarthak AI is ready!" -ForegroundColor Green
Write-Host ""
Write-Host "  Open the Web UI:" -ForegroundColor Green
Write-Host "    http://${webHost}:${webPort}" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Commands:" -ForegroundColor DarkGray
Write-Host "    sarthak service install  - (re)install background orchestrator" -ForegroundColor Yellow
Write-Host "    sarthak --help           - show all commands" -ForegroundColor Yellow
Write-Host ""
