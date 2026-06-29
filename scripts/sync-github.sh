#!/usr/bin/env bash
# Commit meaningful project changes and push to GitHub.
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0
cd "$ROOT"

LOCK="$ROOT/.git/sync-github.lock"
if [[ -f "$LOCK" ]]; then
  exit 0
fi
touch "$LOCK"
trap 'rm -f "$LOCK"' EXIT

should_skip() {
  case "$1" in
    .cursor/*|*.log|models/*|llama.cpp/*|train_data.jsonl|val_data.jsonl|benchmark_results.json|pr.txt)
      return 0
      ;;
  esac
  return 1
}

git add \
  extension/ \
  server.py \
  start_server.sh \
  security.py \
  cloud_ai.py \
  writing_agent.py \
  prepare_data.py \
  scripts/ \
  benchmark_tests.json \
  "Humanizer design system.json" \
  2>/dev/null || true

while IFS= read -r file; do
  [[ -z "$file" ]] && continue
  if should_skip "$file"; then
    continue
  fi
  git add "$file" 2>/dev/null || true
done < <(git diff --name-only)

git restore --staged .cursor/ 2>/dev/null || true

if git diff --cached --quiet; then
  exit 0
fi

git commit -m "Auto-sync: local changes ($(date '+%Y-%m-%d %H:%M'))"

git push origin HEAD
