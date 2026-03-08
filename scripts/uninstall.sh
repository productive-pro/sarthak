#!/usr/bin/env bash
# Sarthak AI — Uninstall (Linux / macOS)
# Removes services, the ~/.sarthak_ai directory, and the sarthak binary.

set -euo pipefail

INSTALL_DIR="$HOME/.sarthak_ai"
BIN_DIR="${SARTHAK_BIN_DIR:-$HOME/.local/bin}"
WRAPPER="$BIN_DIR/sarthak"
SERVICE_NAME="sarthak-orchestrator"
SYSTEMD_USER_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
PLIST_ORCH="$HOME/Library/LaunchAgents/com.sarthak.orchestrator.plist"

OR='\033[38;5;214m'; GR='\033[38;5;82m'; YL='\033[38;5;227m'
RD='\033[38;5;196m'; BD='\033[1m'; RS='\033[0m'

ok()   { printf "  ${GR}+${RS} %s\n" "$*"; }
warn() { printf "  ${YL}!${RS} %s\n" "$*"; }

printf "\n${OR}${BD}  Sarthak AI — Uninstall${RS}\n\n"

# ── Stop and remove services ──────────────────────────────────────────────────
if [[ "$(uname -s)" == "Linux" ]]; then
    systemctl --user stop    "$SERVICE_NAME" 2>/dev/null && ok "Service stopped"     || true
    systemctl --user disable "$SERVICE_NAME" 2>/dev/null && ok "Service disabled"    || true
    rm -f "$SYSTEMD_USER_DIR/$SERVICE_NAME.service"      && ok "Service file removed" || true
    systemctl --user daemon-reload 2>/dev/null || true
fi

if [[ "$(uname -s)" == "Darwin" ]]; then
    launchctl unload "$PLIST_ORCH" 2>/dev/null && ok "launchd agent unloaded" || true
    rm -f "$PLIST_ORCH" && ok "plist removed" || true
fi

# ── Remove binary ─────────────────────────────────────────────────────────────
if [[ -f "$WRAPPER" ]]; then
    rm -f "$WRAPPER"
    ok "Removed $WRAPPER"
else
    warn "$WRAPPER not found (already removed?)"
fi

# Also remove any uv tool install
if command -v uv &>/dev/null; then
    uv tool uninstall sarthak 2>/dev/null && ok "uv tool uninstalled sarthak" || true
fi

# ── Remove config & data ──────────────────────────────────────────────────────
if [[ -d "$INSTALL_DIR" ]]; then
    rm -rf "$INSTALL_DIR"
    ok "Removed $INSTALL_DIR"
else
    warn "$INSTALL_DIR not found (already removed?)"
fi

printf "\n  ${GR}✓${RS}  Sarthak AI uninstalled.\n\n"
