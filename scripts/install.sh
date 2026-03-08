#!/usr/bin/env bash
# Sarthak AI — Full installer (Linux / macOS)
#
# Installs sarthak + orchestrator service.
# Installation modes (checked in order):
#
#   BINARY_INSTALL=1          — download pre-built binary from GitHub Releases (fastest)
#   LOCAL_INSTALL=1           — install from the local repo checkout (dev)
#   RELEASE_TAG=vX.Y.Z        — install that exact version from PyPI via uv tool install
#   (default)                 — install latest from PyPI via uv tool install
#
# Environment variables:
#   SARTHAK_VERSION   — release tag for binary/PyPI install (default: latest)
#   REPO_BRANCH       — branch for source install (default: main)
#   SKIP_WIZARD       — "true" to skip interactive configure wizard
#   SARTHAK_BIN_DIR   — override binary install directory (default: ~/.local/bin)
#   SARTHAK_NO_VERIFY — "1" to skip SHA-256 checksum verification

set -euo pipefail

REPO="1bharath-yadav/sarthak"
REPO_URL="https://github.com/${REPO}"
REPO_BRANCH="${REPO_BRANCH:-main}"
RELEASE_TAG="${RELEASE_TAG:-}"
SARTHAK_VERSION="${SARTHAK_VERSION:-$RELEASE_TAG}"

INSTALL_DIR="$HOME/.sarthak_ai"
CONFIG_FILE="$INSTALL_DIR/config.toml"
ORCHESTRATOR_SERVICE_NAME="sarthak-orchestrator"
SYSTEMD_USER_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
BIN_DIR="${SARTHAK_BIN_DIR:-$HOME/.local/bin}"

OR='\033[38;5;214m'; CY='\033[38;5;87m'; GR='\033[38;5;82m'
YL='\033[38;5;227m'; RD='\033[38;5;196m'; BD='\033[1m'; RS='\033[0m'

hdr()  { printf "\n${OR}${BD}:: %s${RS}\n" "$*"; }
ok()   { printf "  ${GR}+${RS} %s\n" "$*"; }
info() { printf "  ${CY}>${RS} %s\n" "$*"; }
warn() { printf "  ${YL}!${RS} %s\n" "$*"; }
fail() { printf "  ${RD}x${RS} %s\n" "$*"; exit 1; }
step() { printf "\n${CY}${BD}[%s/%s]${RS} ${BD}%s${RS}\n" "$1" "$TOTAL_STEPS" "$2"; }

require_cmd() { command -v "$1" &>/dev/null || fail "Missing required command: $1"; }

OS_NAME="$(uname -s)"
case "$OS_NAME" in
    Linux)  OS_KEY="linux"  ;;
    Darwin) OS_KEY="macos"  ;;
    *)      fail "Unsupported OS: $OS_NAME. Use scripts/install.ps1 on Windows." ;;
esac

ARCH="$(uname -m)"
case "$ARCH" in
    x86_64|amd64)  ARCH_KEY="x86_64"  ;;
    aarch64|arm64) ARCH_KEY="aarch64" ;;
    *)             ARCH_KEY="" ;;
esac

TOTAL_STEPS=5
clear

hdr "Sarthak AI Installer"
info "OS: ${OS_KEY}  Arch: ${ARCH}"

# ── Ensure PATH includes uv/tool bin dirs ─────────────────────────────────────
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"


# ─────────────────────────────────────────────────────────────────────────────
# Helper: resolve latest GitHub release tag
# ─────────────────────────────────────────────────────────────────────────────
_resolve_latest_version() {
    local tag
    if command -v curl &>/dev/null; then
        tag="$(curl -fsSL "https://api.github.com/repos/${REPO}/releases/latest" \
            | grep '"tag_name"' | head -1 | sed 's/.*"tag_name": *"\([^"]*\)".*/\1/')"
    elif command -v wget &>/dev/null; then
        tag="$(wget -qO- "https://api.github.com/repos/${REPO}/releases/latest" \
            | grep '"tag_name"' | head -1 | sed 's/.*"tag_name": *"\([^"]*\)".*/\1/')"
    fi
    echo "$tag"
}

# ─────────────────────────────────────────────────────────────────────────────
# Helper: ensure uv is available
# ─────────────────────────────────────────────────────────────────────────────
_ensure_uv() {
    if ! command -v uv &>/dev/null; then
        info "uv not found — installing …"
        if command -v curl &>/dev/null; then
            curl -LsSf https://astral.sh/uv/install.sh | sh
        else
            wget -qO- https://astral.sh/uv/install.sh | sh
        fi
        export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
        command -v uv &>/dev/null || fail "uv install failed"
        ok "uv installed"
    fi
}

# ─────────────────────────────────────────────────────────────────────────────
# Step 1: Install the sarthak executable
# ─────────────────────────────────────────────────────────────────────────────
step 1 "Installing sarthak"
mkdir -p "$INSTALL_DIR" "$BIN_DIR"

# Determine install mode
BINARY_INSTALL="${BINARY_INSTALL:-0}"
LOCAL_INSTALL="${LOCAL_INSTALL:-0}"

if [[ "$BINARY_INSTALL" == "1" && -z "$ARCH_KEY" ]]; then
    warn "No pre-built binary for arch $ARCH — falling back to PyPI install"
    BINARY_INSTALL="0"
fi

if [[ "$BINARY_INSTALL" == "1" ]]; then
    # ── Mode A: Binary from GitHub Releases ──────────────────────────────────
    [[ -n "$SARTHAK_VERSION" ]] || SARTHAK_VERSION="$(_resolve_latest_version)"
    [[ -n "$SARTHAK_VERSION" ]] || fail "Could not resolve latest release. Set SARTHAK_VERSION=vX.Y.Z"

    ASSET_NAME="sarthak-${OS_KEY}-${ARCH_KEY}"
    BASE_URL="${REPO_URL}/releases/download/${SARTHAK_VERSION}"
    BINARY_URL="${BASE_URL}/${ASSET_NAME}"
    SUMS_URL="${BASE_URL}/SHA256SUMS.txt"

    info "Downloading ${ASSET_NAME} (${SARTHAK_VERSION}) …"
    TMP="$(mktemp -d)"
    trap 'rm -rf "$TMP"' EXIT

    if command -v curl &>/dev/null; then
        curl -fsSL "$BINARY_URL" -o "${TMP}/${ASSET_NAME}"
    else
        wget -qO "${TMP}/${ASSET_NAME}" "$BINARY_URL"
    fi

    if [[ "${SARTHAK_NO_VERIFY:-0}" != "1" ]]; then
        SUMS_TMP="${TMP}/SHA256SUMS.txt"
        { command -v curl &>/dev/null && curl -fsSL "$SUMS_URL" -o "$SUMS_TMP"; } \
            || { command -v wget &>/dev/null && wget -qO "$SUMS_TMP" "$SUMS_URL"; } \
            || true
        if [[ -f "$SUMS_TMP" ]]; then
            EXPECTED="$(grep "${ASSET_NAME}" "$SUMS_TMP" 2>/dev/null | awk '{print $1}')"
            if [[ -n "$EXPECTED" ]]; then
                if command -v sha256sum &>/dev/null; then
                    ACTUAL="$(sha256sum "${TMP}/${ASSET_NAME}" | awk '{print $1}')"
                else
                    ACTUAL="$(shasum -a 256 "${TMP}/${ASSET_NAME}" | awk '{print $1}')"
                fi
                [[ "$ACTUAL" == "$EXPECTED" ]] || fail "Checksum mismatch for ${ASSET_NAME}"
                ok "Checksum verified"
            fi
        fi
    fi

    install -m 0755 "${TMP}/${ASSET_NAME}" "${BIN_DIR}/sarthak"
    ok "Binary installed: ${BIN_DIR}/sarthak  (${SARTHAK_VERSION})"
    SARTHAK_EXEC="${BIN_DIR}/sarthak"

elif [[ "$LOCAL_INSTALL" == "1" ]]; then
    # ── Mode B: Local source (dev) ────────────────────────────────────────────
    SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.."; pwd)"
    info "Local install from $SRC_DIR"
    _ensure_uv
    uv tool install --editable "$SRC_DIR" --extra cloud --force
    SARTHAK_EXEC="$(command -v sarthak 2>/dev/null || echo "${BIN_DIR}/sarthak")"
    ok "Installed from local source: $SARTHAK_EXEC"

elif [[ -n "$RELEASE_TAG" ]]; then
    # ── Mode C: Specific version from PyPI ───────────────────────────────────
    _ensure_uv
    VER="${RELEASE_TAG#v}"
    info "Installing sarthak==${VER} from PyPI …"
    uv tool install "sarthak[cloud]==${VER}" --force
    SARTHAK_EXEC="$(command -v sarthak 2>/dev/null || echo "${BIN_DIR}/sarthak")"
    ok "Installed sarthak==${VER}: $SARTHAK_EXEC"

else
    # ── Mode D: Latest from PyPI (default) ───────────────────────────────────
    _ensure_uv
    info "Installing latest sarthak from PyPI …"
    uv tool install "sarthak[cloud]" --upgrade
    SARTHAK_EXEC="$(command -v sarthak 2>/dev/null || echo "${BIN_DIR}/sarthak")"
    ok "Installed latest sarthak: $SARTHAK_EXEC"
fi

[[ -x "$SARTHAK_EXEC" ]] || fail "sarthak executable not found at $SARTHAK_EXEC"


# ─────────────────────────────────────────────────────────────────────────────
# Step 2: First-run bootstrap
# ─────────────────────────────────────────────────────────────────────────────
step 2 "Setting up ~/.sarthak_ai"
"$SARTHAK_EXEC" status > /dev/null 2>&1 || true
ok "~/.sarthak_ai ready"

# ─────────────────────────────────────────────────────────────────────────────
# Step 3: Interactive configuration wizard
# ─────────────────────────────────────────────────────────────────────────────
step 3 "Configuring Sarthak AI"
if [[ "${SKIP_WIZARD:-}" == "true" ]]; then
    warn "Wizard skipped (SKIP_WIZARD=true) — run 'sarthak configure' later"
else
    info "Launching configuration wizard (Ctrl-C to skip) …"
    "$SARTHAK_EXEC" configure --mode full </dev/tty || warn "Wizard exited early — run 'sarthak configure' later"
fi

# ─────────────────────────────────────────────────────────────────────────────
# Step 4: Install orchestrator service
# ─────────────────────────────────────────────────────────────────────────────
step 4 "Installing orchestrator service"
mkdir -p "$INSTALL_DIR/logs"

# Delegate to the CLI so install.sh and `sarthak service install` share one code path
"$SARTHAK_EXEC" service install || {
    warn "Service install via CLI failed — attempting direct fallback"

    if [[ "$OS_NAME" == "Linux" ]]; then
        require_cmd systemctl
        mkdir -p "$SYSTEMD_USER_DIR"
        cat > "$SYSTEMD_USER_DIR/${ORCHESTRATOR_SERVICE_NAME}.service" <<UNIT
[Unit]
Description=Sarthak AI — Orchestrator
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=90
StartLimitBurst=5

[Service]
Type=simple
WorkingDirectory=${INSTALL_DIR}
ExecStart=${SARTHAK_EXEC} orchestrator
Environment=SARTHAK_CONFIG=${CONFIG_FILE}
Environment=SARTHAK_ORCHESTRATOR_SKIP_CAPTURE=1
Environment=HOME=${HOME}
Environment=PATH=${PATH}
Restart=on-failure
RestartSec=15

[Install]
WantedBy=default.target
UNIT
        systemctl --user daemon-reload
        systemctl --user enable "$ORCHESTRATOR_SERVICE_NAME"
        systemctl --user restart "$ORCHESTRATOR_SERVICE_NAME"
        ok "systemd service enabled and started"

    elif [[ "$OS_NAME" == "Darwin" ]]; then
        LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
        PLIST="${LAUNCH_AGENTS_DIR}/com.sarthak.orchestrator.plist"
        mkdir -p "$LAUNCH_AGENTS_DIR"
        cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.sarthak.orchestrator</string>
  <key>ProgramArguments</key>
  <array>
    <string>${SARTHAK_EXEC}</string>
    <string>orchestrator</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>SARTHAK_CONFIG</key><string>${CONFIG_FILE}</string>
    <key>SARTHAK_ORCHESTRATOR_SKIP_CAPTURE</key><string>1</string>
  </dict>
  <key>WorkingDirectory</key><string>${INSTALL_DIR}</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>${INSTALL_DIR}/logs/orchestrator.log</string>
  <key>StandardErrorPath</key><string>${INSTALL_DIR}/logs/orchestrator.err</string>
</dict>
</plist>
PLIST
        launchctl unload "$PLIST" 2>/dev/null || true
        launchctl load "$PLIST"
        ok "launchd agent installed and started"

    else
        warn "Service auto-install not supported on $OS_NAME"
        info "Run manually: $SARTHAK_EXEC orchestrator"
    fi
}

# ─────────────────────────────────────────────────────────────────────────────
# Step 5: PATH check
# ─────────────────────────────────────────────────────────────────────────────
step 5 "Checking PATH"
if echo ":${PATH}:" | grep -q ":${BIN_DIR}:"; then
    ok "${BIN_DIR} is in your PATH"
else
    warn "${BIN_DIR} is NOT in your PATH — add it:"
    warn "  echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.bashrc && source ~/.bashrc"
fi

hdr "Installation complete"
info "Config & data : ${INSTALL_DIR}"
info "Executable    : ${SARTHAK_EXEC}"
[[ "$OS_NAME" == "Linux" ]] && info "Service       : systemctl --user status ${ORCHESTRATOR_SERVICE_NAME}"

WEB_HOST="127.0.0.1"; WEB_PORT="4848"
if [[ -f "$CONFIG_FILE" ]]; then
    _h=$(grep -E '^\s*host\s*=' "$CONFIG_FILE" | head -1 | sed 's/.*=\s*"\?\([^"]*\)"\?.*/\1/' | tr -d ' ')
    _p=$(grep -E '^\s*port\s*=' "$CONFIG_FILE" | head -1 | sed 's/.*=\s*\([0-9]*\).*/\1/' | tr -d ' ')
    [[ -n "$_h" ]] && WEB_HOST="$_h"
    [[ -n "$_p" ]] && WEB_PORT="$_p"
fi
[[ "$WEB_HOST" == "127.0.0.1" || "$WEB_HOST" == "0.0.0.0" ]] && WEB_HOST="localhost"

printf "\n${OR}${BD}  ✓  Sarthak AI is ready!${RS}\n"
printf "\n  ${GR}Open the Web UI:${RS}\n"
printf "    ${CY}${BD}http://${WEB_HOST}:${WEB_PORT}${RS}\n"
printf "\n  Commands:\n"
printf "    ${OR}sarthak service install${RS}  (re)install background orchestrator\n"
printf "    ${OR}sarthak --help${RS}           show all commands\n\n"
