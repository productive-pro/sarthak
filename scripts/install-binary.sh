#!/usr/bin/env bash
# Sarthak AI — Binary installer (Linux / macOS)
#
# Downloads the correct pre-built binary from GitHub Releases,
# verifies its SHA-256 checksum, and installs to ~/.local/bin/sarthak.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/1bharath-yadav/sarthak/main/scripts/install-binary.sh | bash
#
# Install a specific version:
#   SARTHAK_VERSION=v1.2.3 curl -fsSL ... | bash
#
# Install to a custom location:
#   SARTHAK_BIN_DIR=/usr/local/bin curl -fsSL ... | bash
#
# Skip checksum verification (not recommended):
#   SARTHAK_NO_VERIFY=1 curl -fsSL ... | bash

set -euo pipefail

REPO="1bharath-yadav/sarthak"
RELEASES_URL="https://github.com/${REPO}/releases"
API_URL="https://api.github.com/repos/${REPO}/releases"

SARTHAK_VERSION="${SARTHAK_VERSION:-}"
BIN_DIR="${SARTHAK_BIN_DIR:-$HOME/.local/bin}"
NO_VERIFY="${SARTHAK_NO_VERIFY:-0}"

# ── Palette ───────────────────────────────────────────────────────────────────
OR='\033[38;5;214m'; CY='\033[38;5;87m'; GR='\033[38;5;82m'
YL='\033[38;5;227m'; RD='\033[38;5;196m'; BD='\033[1m'; RS='\033[0m'

info() { printf "  ${CY}>${RS} %s\n" "$*"; }
ok()   { printf "  ${GR}✓${RS} %s\n" "$*"; }
warn() { printf "  ${YL}!${RS} %s\n" "$*"; }
fail() { printf "  ${RD}✗${RS} %s\n" "$*"; exit 1; }
hdr()  { printf "\n${OR}${BD}  %s${RS}\n\n" "$*"; }

# ── Detect OS ─────────────────────────────────────────────────────────────────
OS="$(uname -s)"
case "$OS" in
    Linux)  OS_KEY="linux"  ;;
    Darwin) OS_KEY="macos"  ;;
    *)      fail "Unsupported OS: $OS. Use scripts/install-binary.ps1 on Windows." ;;
esac

# ── Detect architecture ───────────────────────────────────────────────────────
ARCH="$(uname -m)"
case "$ARCH" in
    x86_64 | amd64)          ARCH_KEY="x86_64"  ;;
    aarch64 | arm64)         ARCH_KEY="aarch64" ;;
    *)                       fail "Unsupported architecture: $ARCH" ;;
esac

ASSET_NAME="sarthak-${OS_KEY}-${ARCH_KEY}"

hdr "Sarthak AI Installer"
info "Platform : ${OS_KEY}/${ARCH_KEY}"
info "Binary   : ${ASSET_NAME}"
info "Install  : ${BIN_DIR}/sarthak"

# ── Require curl or wget ──────────────────────────────────────────────────────
if command -v curl &>/dev/null; then
    _get() { curl -fsSL "$1" -o "$2"; }
    _get_stdout() { curl -fsSL "$1"; }
elif command -v wget &>/dev/null; then
    _get() { wget -qO "$2" "$1"; }
    _get_stdout() { wget -qO- "$1"; }
else
    fail "curl or wget is required. Install one and re-run."
fi

# ── Resolve version ───────────────────────────────────────────────────────────
if [[ -z "$SARTHAK_VERSION" ]]; then
    info "Fetching latest release tag …"
    # Works without auth; rate-limited to 60 req/h unauthenticated
    SARTHAK_VERSION="$(_get_stdout "${API_URL}/latest" | grep '"tag_name"' | head -1 | sed 's/.*"tag_name": *"\([^"]*\)".*/\1/')"
    [[ -n "$SARTHAK_VERSION" ]] || fail "Could not determine latest release. Set SARTHAK_VERSION=vX.Y.Z"
fi

ok "Version  : ${SARTHAK_VERSION}"

BASE_URL="${RELEASES_URL}/download/${SARTHAK_VERSION}"
BINARY_URL="${BASE_URL}/${ASSET_NAME}"
SUMS_URL="${BASE_URL}/SHA256SUMS.txt"

# ── Download to temp dir ──────────────────────────────────────────────────────
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

BINARY_TMP="${TMP}/${ASSET_NAME}"
SUMS_TMP="${TMP}/SHA256SUMS.txt"

info "Downloading binary …"
_get "$BINARY_URL" "$BINARY_TMP" || fail "Download failed: ${BINARY_URL}"
ok "Downloaded $(du -sh "$BINARY_TMP" | cut -f1)"

# ── Verify SHA-256 checksum ───────────────────────────────────────────────────
if [[ "$NO_VERIFY" == "1" ]]; then
    warn "Checksum verification skipped (SARTHAK_NO_VERIFY=1)"
else
    info "Verifying SHA-256 checksum …"
    _get "$SUMS_URL" "$SUMS_TMP" || { warn "SHA256SUMS.txt not found — skipping verification"; NO_VERIFY=1; }

    if [[ "$NO_VERIFY" != "1" ]]; then
        EXPECTED="$(grep "${ASSET_NAME}" "$SUMS_TMP" | awk '{print $1}')"
        if [[ -z "$EXPECTED" ]]; then
            warn "Checksum for ${ASSET_NAME} not found in SHA256SUMS.txt — skipping"
        else
            if command -v sha256sum &>/dev/null; then
                ACTUAL="$(sha256sum "$BINARY_TMP" | awk '{print $1}')"
            else
                ACTUAL="$(shasum -a 256 "$BINARY_TMP" | awk '{print $1}')"
            fi
            [[ "$ACTUAL" == "$EXPECTED" ]] || fail "Checksum mismatch!
  Expected : ${EXPECTED}
  Got      : ${ACTUAL}
  File may be corrupted. Re-run or download manually from:
  ${BINARY_URL}"
            ok "Checksum verified"
        fi
    fi
fi

# ── Install ───────────────────────────────────────────────────────────────────
mkdir -p "$BIN_DIR"
install -m 0755 "$BINARY_TMP" "${BIN_DIR}/sarthak"
ok "Installed → ${BIN_DIR}/sarthak"

# ── PATH check ────────────────────────────────────────────────────────────────
printf "\n"
if echo ":${PATH}:" | grep -q ":${BIN_DIR}:"; then
    ok "${BIN_DIR} is in your PATH"
else
    warn "${BIN_DIR} is not in your PATH"
    warn "Add it by running one of:"
    warn "  echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.bashrc && source ~/.bashrc"
    warn "  echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.zshrc  && source ~/.zshrc"
fi

# ── First-run setup (bootstrap) ───────────────────────────────────────────────
printf "\n"
info "Running first-time setup …"
"${BIN_DIR}/sarthak" --help > /dev/null 2>&1 && ok "sarthak is working" || warn "Could not run sarthak — check the binary"

printf "\n"
hdr "Done!"
info "Run  ${OR}${BD}sarthak configure${RS}  to choose your AI provider."
info "Run  ${OR}${BD}sarthak --help${RS}      to see all commands."
printf "\n"
