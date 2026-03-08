#!/usr/bin/env bash
set -euo pipefail

if command -v sarthak >/dev/null 2>&1; then
  sarthak status
  exit 0
fi

BIN="$HOME/.local/bin/sarthak"
if [[ -x "$BIN" ]]; then
  "$BIN" status
  exit 0
fi

echo "sarthak not found in PATH."
exit 1
