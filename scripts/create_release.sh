#!/usr/bin/env bash
# Build extension zips + macOS app and create/update a GitHub Release (requires gh CLI).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if ! command -v gh >/dev/null 2>&1; then
  echo "Error: GitHub CLI (gh) required. Install: brew install gh"
  exit 1
fi

bash "$ROOT/scripts/package_extension.sh"
bash "$ROOT/scripts/build_macos_app.sh"

VERSION="$(python3 -c "import json; print(json.load(open('extension/manifest.json'))['version'])")"
TAG="v${VERSION}"
MAC_ZIP="$ROOT/dist/thoth-extension-mac-v${VERSION}.zip"
WIN_ZIP="$ROOT/dist/thoth-extension-windows-v${VERSION}.zip"
GENERIC_ZIP="$ROOT/dist/thoth-extension-v${VERSION}.zip"
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

for f in "$MAC_ZIP" "$WIN_ZIP" "$GENERIC_ZIP" "$APP_ZIP" "$APP_ZIP_STABLE"; do
  if [[ ! -f "$f" ]]; then
    echo "Error: $f not found"
    exit 1
  fi
done

NOTES="$(cat <<EOF
# Thoth ${TAG}

Chrome extension + local writing server for **Windows** and **macOS**.

## macOS — menu bar app (recommended)

1. Download **[Thoth-macOS.zip](https://github.com/Eshan-khan1/Thoth/releases/download/${TAG}/Thoth-macOS.zip)**
2. Download **[thoth-extension-mac-v${VERSION}.zip](https://github.com/Eshan-khan1/Thoth/releases/download/${TAG}/thoth-extension-mac-v${VERSION}.zip)**
3. Unzip the app zip → drag **Thoth.app** into **Applications** → open it once
4. Unzip the extension → Chrome → \`chrome://extensions\` → **Developer mode** → **Load unpacked**
5. Leave the menu bar icon running; it starts the server and relaunches after login

Full guide: **[Install on Mac](https://github.com/Eshan-khan1/Thoth/blob/main/docs/INSTALL_MAC.md)**

## Windows

1. Download **[thoth-extension-windows-v${VERSION}.zip](https://github.com/Eshan-khan1/Thoth/releases/download/${TAG}/thoth-extension-windows-v${VERSION}.zip)**
2. Follow **[Install on Windows](https://github.com/Eshan-khan1/Thoth/blob/main/docs/INSTALL_WINDOWS.md)** (clone the repo, run \`scripts\\install.bat\`, then \`Start Thoth.bat\`)

## Health check

http://127.0.0.1:8000/health should show \`"ok": true\`.
EOF
)"

ASSETS=(
  "$APP_ZIP"
  "$APP_ZIP_STABLE"
  "$MAC_ZIP"
  "$WIN_ZIP"
  "$GENERIC_ZIP"
  "$ROOT/dist/README-WINDOWS.txt"
  "$ROOT/dist/README-MAC.txt"
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
