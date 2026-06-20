#!/bin/bash
# Launch Chrome with the Humanizer extension loaded (dev profile).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PROFILE="${HOME}/.humanizer-chrome-dev"
EXT="${ROOT}/extension"
TEST_PAGE="file://${ROOT}/test_data/rewrite_test.html"

if [[ ! -x "$CHROME" ]]; then
  echo "Google Chrome not found at $CHROME" >&2
  exit 1
fi

mkdir -p "$PROFILE"

# Close prior dev Chrome using this profile only.
pkill -f "${PROFILE}" 2>/dev/null || true
sleep 0.5

exec "$CHROME" \
  --user-data-dir="$PROFILE" \
  --load-extension="$EXT" \
  --no-first-run \
  --no-default-browser-check \
  "$TEST_PAGE"
