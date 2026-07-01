#!/usr/bin/env bash
# Build extension zip and create a GitHub Release (requires gh CLI).
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
ZIP="$ROOT/dist/humanizer-extension-v${VERSION}.zip"

if [[ ! -f "$ZIP" ]]; then
  echo "Error: $ZIP not found"
  exit 1
fi

NOTES="Humanizer Chrome extension v${VERSION}

## Install
1. Download \`humanizer-extension-v${VERSION}.zip\` below
2. Unzip the file
3. Chrome → chrome://extensions → Developer mode → Load unpacked → select the unzipped folder
4. Clone https://github.com/Eshan-khan1/Humanizer and run \`./scripts/install.sh\` then \`./start_server.sh\`

See README.md for full setup."

if gh release view "$TAG" >/dev/null 2>&1; then
  echo "==> Updating release $TAG..."
  gh release upload "$TAG" "$ZIP" --clobber
else
  echo "==> Creating release $TAG..."
  gh release create "$TAG" "$ZIP" \
    --title "Humanizer ${TAG}" \
    --notes "$NOTES"
fi

echo "Release: https://github.com/Eshan-khan1/Humanizer/releases/tag/${TAG}"
