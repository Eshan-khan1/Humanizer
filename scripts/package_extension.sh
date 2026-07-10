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
  local out="$DIST/humanizer-extension-${label}-v${VERSION}.zip"
  echo "==> Packaging Humanizer extension v${VERSION} (${label})..."
  (
    cd "$EXT"
    zip -r "$out" . \
      -x "*.DS_Store" \
      -x "__MACOSX/*" \
      -x "*.git/*"
  )
  echo "  $out"
}

package_one "mac"
package_one "windows"

# Generic latest alias (same bytes as mac/windows — extension is cross-platform)
cp "$DIST/humanizer-extension-mac-v${VERSION}.zip" "$DIST/humanizer-extension.zip"
cp "$DIST/humanizer-extension-mac-v${VERSION}.zip" "$DIST/humanizer-extension-v${VERSION}.zip"

# Starter note files bundled beside zips for release clarity
cat > "$DIST/README-WINDOWS.txt" <<EOF
Humanizer for Windows
=====================

1. Install Python 3.10+ (Add to PATH), Ollama, and Java 11+.
2. Clone or download the full Humanizer repo from GitHub.
3. Run scripts\\install.bat then Start Humanizer.bat
4. Unzip this extension zip (or use the repo's extension\\ folder).
5. Chrome → chrome://extensions → Developer mode → Load unpacked → select the unzipped folder.

Full guide: docs/INSTALL_WINDOWS.md in the repo
https://github.com/Eshan-khan1/Humanizer/blob/main/docs/INSTALL_WINDOWS.md
EOF

cat > "$DIST/README-MAC.txt" <<EOF
Humanizer for macOS
===================

1. Install Python 3.10+, Ollama, and Java 11+ (e.g. brew install openjdk@17).
2. Clone the Humanizer repo.
3. Run ./scripts/install.sh then ./start_server.sh (or double-click Start Humanizer.command).
4. Unzip this extension zip (or use the repo's extension/ folder).
5. Chrome → chrome://extensions → Developer mode → Load unpacked → select the unzipped folder.

Full guide: docs/INSTALL_MAC.md in the repo
https://github.com/Eshan-khan1/Humanizer/blob/main/docs/INSTALL_MAC.md
EOF

echo ""
echo "Built release assets in dist/"
ls -la "$DIST"
