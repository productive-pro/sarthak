#!/usr/bin/env bash
# Sarthak AI — Build standalone binary (Linux / macOS)
#
# Uses PyInstaller to produce a single-file executable that includes:
#   • All Python code + dependencies
#   • providers.json  (AI model catalog)
#   • config.toml     (default config template)
#   • prompts.json    (system prompts)
#
# Usage:
#   bash scripts/build_binary.sh                 # output: dist/sarthak
#   ASSET_NAME=sarthak-linux-x86_64 bash ...     # output: dist/sarthak-linux-x86_64
#
# Requirements: pyinstaller in PATH or venv
#   pip install pyinstaller   OR   uv pip install pyinstaller

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST_DIR="$REPO_ROOT/dist"
BUILD_DIR="$REPO_ROOT/build"
ASSET_NAME="${ASSET_NAME:-sarthak}"

cd "$REPO_ROOT"

echo "  > Building Sarthak binary: $ASSET_NAME"
echo "  > Repo root : $REPO_ROOT"
echo "  > Output    : $DIST_DIR/$ASSET_NAME"

# ── Resolve PyInstaller ───────────────────────────────────────────────────────
if command -v pyinstaller &>/dev/null; then
    PYI="pyinstaller"
elif python -m PyInstaller --version &>/dev/null 2>&1; then
    PYI="python -m PyInstaller"
else
    echo "ERROR: pyinstaller not found. Install with: pip install pyinstaller"
    exit 1
fi

# ── Collect data file paths (sep is OS-aware : vs ;) ─────────────────────────
SEP=":"

DATA_FILES=(
    "$REPO_ROOT/src/sarthak/data/providers.json${SEP}sarthak/data"
    "$REPO_ROOT/src/sarthak/data/config.toml${SEP}sarthak/data"
    "$REPO_ROOT/src/sarthak/core/ai_utils/prompts.json${SEP}sarthak/core/ai_utils"
)

ADD_DATA_ARGS=()
for item in "${DATA_FILES[@]}"; do
    ADD_DATA_ARGS+=(--add-data "$item")
done

# ── Hidden imports that PyInstaller's static analysis misses ─────────────────
HIDDEN=(
    sarthak.cli
    sarthak.cli.spaces_cli
    sarthak.cli.agents_cli
    sarthak.cli.analytics_cli
    sarthak.core.setup
    sarthak.core.configure
    sarthak.core.config
    sarthak.core.ai_utils.catalog
    sarthak.core.ai_utils.multi_provider
    sarthak.core.ai_utils.provider_registry
    sarthak.storage.encrypt
    sarthak.spaces.store
    tomlkit
    questionary
    structlog
    aiosqlite
    pydantic_ai
    cryptography
    httpx
)

HIDDEN_ARGS=()
for mod in "${HIDDEN[@]}"; do
    HIDDEN_ARGS+=(--hidden-import "$mod")
done

# ── Run PyInstaller ───────────────────────────────────────────────────────────
mkdir -p "$DIST_DIR"

$PYI \
    --onefile \
    --name sarthak \
    --distpath "$DIST_DIR" \
    --workpath "$BUILD_DIR/pyinstaller_work" \
    --specpath "$BUILD_DIR" \
    --noconfirm \
    --clean \
    "${ADD_DATA_ARGS[@]}" \
    "${HIDDEN_ARGS[@]}" \
    --collect-all sarthak \
    --collect-all pydantic_ai \
    --collect-data textual \
    --collect-data rich \
    "src/sarthak/cli/__main__.py"

# ── Rename to ASSET_NAME if provided ─────────────────────────────────────────
if [[ "$ASSET_NAME" != "sarthak" && -f "$DIST_DIR/sarthak" ]]; then
    mv "$DIST_DIR/sarthak" "$DIST_DIR/$ASSET_NAME"
fi

echo ""
echo "  ✓ Binary: $DIST_DIR/$ASSET_NAME"
ls -lh "$DIST_DIR/$ASSET_NAME"
