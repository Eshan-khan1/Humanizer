#!/usr/bin/env bash
# Build a Chrome Web Store upload zip (developers only — not published on GitHub Releases).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
EXT="$ROOT/extension"
DIST="$ROOT/dist"
CHROME_STORE_URL="https://chromewebstore.google.com/detail/begfbbjincimcjcimpfpkoilbhjphppn?utm_source=item-share-cb"

if [[ ! -f "$EXT/manifest.json" ]]; then
  echo "Error: extension/manifest.json not found"
  exit 1
fi

VERSION="$(python3 -c "import json; print(json.load(open('$EXT/manifest.json'))['version'])")"
mkdir -p "$DIST"

OUT="$DIST/thoth-chrome-store-v${VERSION}.zip"
STAGE="$DIST/.ext-stage-store"

echo "==> Packaging Chrome Web Store upload zip v${VERSION}..."
echo "    Public install link: ${CHROME_STORE_URL}"
rm -rf "$STAGE"
mkdir -p "$STAGE"
rsync -a --exclude '.DS_Store' --exclude '__MACOSX' --exclude '.git' "$EXT/" "$STAGE/"
# Chrome Web Store rejects "key" in manifest (keep key in repo for local unpacked ID).
python3 -c "import json,pathlib; p=pathlib.Path('$STAGE/manifest.json'); d=json.loads(p.read_text()); d.pop('key', None); p.write_text(json.dumps(d, indent=2)+'\n')"
(
  cd "$STAGE"
  zip -r "$OUT" . \
    -x "*.DS_Store" \
    -x "__MACOSX/*" \
    -x "*.git/*"
)
rm -rf "$STAGE"

echo "  $OUT"
echo ""
echo "Upload this zip to the Chrome Web Store developer dashboard."
echo "Users install from: ${CHROME_STORE_URL}"
