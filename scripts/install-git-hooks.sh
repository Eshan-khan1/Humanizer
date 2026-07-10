#!/usr/bin/env bash
# Install git hooks for local ↔ GitHub auto-sync.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

install_hook() {
  local name="$1"
  cp "$ROOT/.githooks/$name" "$ROOT/.git/hooks/$name"
  chmod +x "$ROOT/.git/hooks/$name"
}

install_hook post-commit
install_hook post-merge

chmod +x \
  "$ROOT/scripts/pull-github.sh" \
  "$ROOT/scripts/sync-github.sh" \
  "$ROOT/scripts/sync-all.sh" \
  "$ROOT/.cursor/hooks/sync-github.sh" \
  "$ROOT/.cursor/hooks/pull-github.sh"

echo "Git hooks installed (post-commit push, post-merge fetch)."
