#!/usr/bin/env bash
# rebuild_frontend.sh — Build React frontend and copy to FastAPI serving dir
set -e

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
FRONTEND_DIR="$ROOT_DIR/frontend"
DEST_DIR="$ROOT_DIR/src/sarthak/web/react_dist"

echo "▶ Building React frontend..."
cd "$FRONTEND_DIR"
npm ci --include=dev
npm run build

echo "▶ Deploying to $DEST_DIR..."
rm -rf "$DEST_DIR"
mkdir -p "$(dirname "$DEST_DIR")"
cp -r dist "$DEST_DIR"

echo "✓ Done. Restart sarthak to use the new build."
