#!/usr/bin/env bash
# Build extension zips and create/update a GitHub Release (requires gh CLI).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if ! command -v gh >/dev/null 2>&1; then
  echo "Error: GitHub CLI (gh) required. Install: brew install gh"
  exit 1
fi

bash "$ROOT/scripts/package_extension.sh"

VERSION="$(python3 -c "import json; print(json.load(open('extension/manifest.json'))['version'])")"
TAG="v${VERSION}"
MAC_ZIP="$ROOT/dist/humanizer-extension-mac-v${VERSION}.zip"
WIN_ZIP="$ROOT/dist/humanizer-extension-windows-v${VERSION}.zip"
GENERIC_ZIP="$ROOT/dist/humanizer-extension-v${VERSION}.zip"

for f in "$MAC_ZIP" "$WIN_ZIP" "$GENERIC_ZIP"; do
  if [[ ! -f "$f" ]]; then
    echo "Error: $f not found"
    exit 1
  fi
done

NOTES="$(cat <<EOF
# Humanizer ${TAG}

Chrome extension + local writing server for **Windows** and **macOS**.

## Install the extension

1. Download the zip for your platform below (or the generic \`humanizer-extension-v${VERSION}.zip\` — same extension).
2. Unzip it.
3. Chrome → \`chrome://extensions\` → **Developer mode** → **Load unpacked** → select the unzipped folder.

## Run the local server

You still need the full repo for the Python server:

\`\`\`bash
git clone https://github.com/Eshan-khan1/Humanizer.git
cd Humanizer
\`\`\`

### Windows
See **[docs/INSTALL_WINDOWS.md](https://github.com/Eshan-khan1/Humanizer/blob/main/docs/INSTALL_WINDOWS.md)**

1. \`scripts\\install.bat\`
2. Open Ollama, then \`scripts\\setup_models.bat\` if needed
3. Double-click \`Start Humanizer.bat\`

### macOS
See **[docs/INSTALL_MAC.md](https://github.com/Eshan-khan1/Humanizer/blob/main/docs/INSTALL_MAC.md)**

1. \`./scripts/install.sh\`
2. \`./start_server.sh\` (or double-click \`Start Humanizer.command\`)

Health check: http://127.0.0.1:8000/health
EOF
)"

ASSETS=(
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
    --title "Humanizer ${TAG}" \
    --notes "$NOTES"
fi

echo "Release: https://github.com/Eshan-khan1/Humanizer/releases/tag/${TAG}"
