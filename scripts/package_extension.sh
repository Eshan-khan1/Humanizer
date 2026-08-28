#!/usr/bin/env bash
# Build platform-labeled Chrome extension zips for GitHub Releases.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
EXT="$ROOT/extension"
DIST="$ROOT/dist"

if [[ ! -f "$EXT/manifest.json" ]]; then
  echo "Error: extension/manifest.json not found"
  exit 1
fi

VERSION="$(python3 -c "import json; print(json.load(open('$EXT/manifest.json'))['version'])")"
mkdir -p "$DIST"

package_one() {
  local label="$1"
  local out="$DIST/thoth-extension-${label}-v${VERSION}.zip"
  local stage="$DIST/.ext-stage-${label}"
  echo "==> Packaging Thoth extension v${VERSION} (${label})..."
  rm -rf "$stage"
  mkdir -p "$stage"
  rsync -a --exclude '.DS_Store' --exclude '__MACOSX' --exclude '.git' "$EXT/" "$stage/"
  # Chrome Web Store rejects "key" in manifest (keep key in repo for local unpacked ID).
  python3 -c "import json,pathlib; p=pathlib.Path('$stage/manifest.json'); d=json.loads(p.read_text()); d.pop('key', None); p.write_text(json.dumps(d, indent=2)+'\n')"
  (
    cd "$stage"
    zip -r "$out" . \
      -x "*.DS_Store" \
      -x "__MACOSX/*" \
      -x "*.git/*"
  )
  rm -rf "$stage"
  echo "  $out"
}

package_one "mac"
package_one "windows"

# Generic latest alias (same bytes as mac/windows — extension is cross-platform)
cp "$DIST/thoth-extension-mac-v${VERSION}.zip" "$DIST/thoth-extension.zip"
cp "$DIST/thoth-extension-mac-v${VERSION}.zip" "$DIST/thoth-extension-v${VERSION}.zip"

# Starter note files bundled beside zips for release clarity
cat > "$DIST/README-WINDOWS.txt" <<EOF
Thoth for Windows
=====================

1. Install Python 3.10+ (Add to PATH), Ollama, and Java 11+.
2. Clone or download the full Thoth repo from GitHub.
3. Run scripts\\install.bat then Start Thoth.bat
4. Install the Chrome extension from the Web Store (do not use a GitHub zip):
   https://chromewebstore.google.com/detail/begfbbjincimcjcimpfpkoilbhjphppn?utm_source=item-share-cb

Full guide: docs/INSTALL_WINDOWS.md in the repo
https://github.com/Eshan-khan1/Thoth/blob/main/docs/INSTALL_WINDOWS.md
EOF

cat > "$DIST/README-MAC.txt" <<EOF
Thoth for macOS
===================

1. Install Python 3.10+, Ollama, and Java 11+ (e.g. brew install openjdk@17).
2. Download Thoth-macOS.zip from the GitHub release:
   https://github.com/Eshan-khan1/Thoth/releases/latest
3. Unzip, drag Thoth.app into Applications, and open it once.
4. Install the Chrome extension from the Web Store (do not use a GitHub zip):
   https://chromewebstore.google.com/detail/begfbbjincimcjcimpfpkoilbhjphppn?utm_source=item-share-cb

The menu bar app starts the local server and relaunches after login.

Full guide: docs/INSTALL_MAC.md in the repo
https://github.com/Eshan-khan1/Thoth/blob/main/docs/INSTALL_MAC.md
EOF

echo ""
echo "Built release assets in dist/"
ls -la "$DIST"
