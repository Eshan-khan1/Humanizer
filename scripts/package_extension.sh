#!/usr/bin/env bash
# Build a zip of the Chrome extension for distribution.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
EXT="$ROOT/extension"
DIST="$ROOT/dist"

if [[ ! -f "$EXT/manifest.json" ]]; then
  echo "Error: extension/manifest.json not found"
  exit 1
fi

VERSION="$(python3 -c "import json; print(json.load(open('$EXT/manifest.json'))['version'])")"
OUT="$DIST/humanizer-extension-v${VERSION}.zip"
LATEST="$DIST/humanizer-extension.zip"

mkdir -p "$DIST"

echo "==> Packaging Humanizer extension v${VERSION}..."

(
  cd "$EXT"
  zip -r "$OUT" . \
    -x "*.DS_Store" \
    -x "__MACOSX/*" \
    -x "*.git/*"
)

cp "$OUT" "$LATEST"

echo "Built:"
echo "  $OUT"
echo "  $LATEST"
echo ""
echo "Share the zip with users. They should:"
echo "  1. Unzip"
echo "  2. chrome://extensions → Developer mode → Load unpacked → select folder"
