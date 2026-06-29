#!/usr/bin/env bash
# One-time setup: push to GitHub after every local commit.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cp "$ROOT/.githooks/post-commit" "$ROOT/.git/hooks/post-commit"
chmod +x "$ROOT/.git/hooks/post-commit" "$ROOT/scripts/sync-github.sh" "$ROOT/.cursor/hooks/sync-github.sh"
echo "Git hooks installed."
