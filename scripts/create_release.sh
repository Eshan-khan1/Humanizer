#!/usr/bin/env bash
# Build macOS app and create/update a GitHub Release (requires gh CLI).
# Chrome extension: install from the Web Store only (not bundled in releases).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

CHROME_STORE_URL="https://chromewebstore.google.com/detail/begfbbjincimcjcimpfpkoilbhjphppn?utm_source=item-share-cb"

if ! command -v gh >/dev/null 2>&1; then
  echo "Error: GitHub CLI (gh) required. Install: brew install gh"
  exit 1
fi

bash "$ROOT/scripts/build_macos_app.sh"

VERSION="$(python3 -c "import json; print(json.load(open('extension/manifest.json'))['version'])")"
TAG="v${VERSION}"
APP_ZIP="$ROOT/dist/Thoth-macOS-v${VERSION}.zip"
APP_ZIP_STABLE="$ROOT/dist/Thoth-macOS.zip"

if [[ ! -d "$ROOT/dist/Thoth.app" ]]; then
  echo "Error: dist/Thoth.app not found"
  exit 1
fi

echo "==> Zipping Thoth.app"
rm -f "$APP_ZIP" "$APP_ZIP_STABLE"
(
  cd "$ROOT/dist"
  ditto -c -k --keepParent Thoth.app "Thoth-macOS-v${VERSION}.zip"
  cp "Thoth-macOS-v${VERSION}.zip" "Thoth-macOS.zip"
)

for f in "$APP_ZIP" "$APP_ZIP_STABLE"; do
  if [[ ! -f "$f" ]]; then
    echo "Error: $f not found"
    exit 1
  fi
done

# Starter notes bundled with the Mac app release (extension = Web Store only)
cat > "$ROOT/dist/README-MAC.txt" <<EOF
Thoth for macOS
===================

1. Install Python 3.10+, Ollama, and Java 11+ (e.g. brew install openjdk@17).
2. Download Thoth-macOS.zip from this release (or latest):
   https://github.com/Eshan-khan1/Thoth/releases/latest
3. Unzip, drag Thoth.app into Applications, and open it once.
4. Install the Chrome extension:
   ${CHROME_STORE_URL}

Full guide: https://github.com/Eshan-khan1/Thoth/blob/main/docs/INSTALL_MAC.md
EOF

cat > "$ROOT/dist/README-WINDOWS.txt" <<EOF
Thoth for Windows
=====================

1. Install Python 3.10+ (Add to PATH), Ollama, and Java 11+.
2. Clone or download the Thoth repo from GitHub.
3. Run scripts\\install.bat then Start Thoth.bat
4. Install the Chrome extension:
   ${CHROME_STORE_URL}

Full guide: https://github.com/Eshan-khan1/Thoth/blob/main/docs/INSTALL_WINDOWS.md
EOF

NOTES="$(cat <<EOF
# Thoth ${TAG}

Local writing server for **Windows** and **macOS**.

## Chrome extension

**[Install Thoth from the Chrome Web Store](${CHROME_STORE_URL})**

## macOS — menu bar app

1. Download **[Thoth-macOS.zip](https://github.com/Eshan-khan1/Thoth/releases/download/${TAG}/Thoth-macOS.zip)**
2. Unzip → drag **Thoth.app** into **Applications** → open it once
3. Install the extension from the Chrome Web Store link above

Full guide: **[Install on Mac](https://github.com/Eshan-khan1/Thoth/blob/main/docs/INSTALL_MAC.md)**

## Windows

1. Follow **[Install on Windows](https://github.com/Eshan-khan1/Thoth/blob/main/docs/INSTALL_WINDOWS.md)** (clone the repo, run \`scripts\\install.bat\`, then \`Start Thoth.bat\`)
2. Install the extension from the Chrome Web Store link above

## Health check

http://127.0.0.1:8000/health should show \`"ok": true\`.
EOF
)"

ASSETS=(
  "$APP_ZIP"
  "$APP_ZIP_STABLE"
  "$ROOT/dist/README-MAC.txt"
  "$ROOT/dist/README-WINDOWS.txt"
)

if gh release view "$TAG" >/dev/null 2>&1; then
  echo "==> Updating release $TAG..."
  gh release upload "$TAG" "${ASSETS[@]}" --clobber
  gh release edit "$TAG" --notes "$NOTES"
else
  echo "==> Creating release $TAG..."
  gh release create "$TAG" "${ASSETS[@]}" \
    --title "Thoth ${TAG}" \
    --notes "$NOTES"
fi

echo "Release: https://github.com/Eshan-khan1/Thoth/releases/tag/${TAG}"
echo "Mac app: https://github.com/Eshan-khan1/Thoth/releases/download/${TAG}/Thoth-macOS.zip"
echo "Extension: ${CHROME_STORE_URL}"
