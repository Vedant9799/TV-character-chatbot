#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UI_DIR="$ROOT_DIR/ui"
DIST_DIR="$UI_DIR/dist"
STATIC_DIR="$ROOT_DIR/static"

if ! command -v npm >/dev/null 2>&1; then
  echo "ERROR: npm is not installed."
  exit 1
fi

if [[ ! -d "$UI_DIR" ]]; then
  echo "ERROR: ui/ directory not found."
  exit 1
fi

cd "$UI_DIR"

if [[ ! -d node_modules ]]; then
  echo "Installing UI dependencies..."
  npm ci
fi

echo "Building UI..."
npm run build

echo "Refreshing static/..."
rm -rf "$STATIC_DIR"
mkdir -p "$STATIC_DIR"
cp -R "$DIST_DIR"/. "$STATIC_DIR"/

echo "Done. static/ is now in sync with ui/."
