#!/usr/bin/env bash
# Bidirectional GitHub sync: pull latest, commit local changes, push to origin.
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0
cd "$ROOT"

LOCK="$ROOT/.git/sync-github.lock"
if [[ -f "$LOCK" ]]; then
  exit 0
fi
touch "$LOCK"
trap 'rm -f "$LOCK"' EXIT

# 1) Pull latest from GitHub first (cloud/local → this workspace).
bash "$ROOT/scripts/pull-github.sh" 2>/dev/null || true

should_skip() {
  case "$1" in
    .cursor/debug*.log|.cursor/*.log|.venv/*|__pycache__/*|*.pyc|models/*|llama.cpp/*|\
    train_data.jsonl|val_data.jsonl|benchmark_results.json|pr.txt|auto_tune.log|*.log|dist/*|build/*)
      return 0
      ;;
  esac
  return 1
}

stage_project_paths() {
  git add -u 2>/dev/null || true

  local paths=(
    extension/
    web/
    scripts/
    test_data/
    .cursor/hooks/
    .cursor/hooks.json
    .cursor/environment.json
    .githooks/
    "ux design/"
    AGENTS.md
    README.md
    Features.txt
    "Humanizer design system.json"
    "Start Humanizer.bat"
    "Start Humanizer.command"
    benchmark_tests.json
    grammar_rules.json
    requirements.txt
    requirements-finetune.txt
    rewriting\ feature.json
    start_server.sh
    run.sh
  )

  local path
  for path in "${paths[@]}"; do
    [[ -e "$path" ]] && git add "$path" 2>/dev/null || true
  done

  while IFS= read -r file; do
    [[ -f "$file" ]] || continue
    case "$file" in
      *.py|*.sh|*.bat|*.command|*.html|*.css|*.js|*.json|*.txt|*.md)
        should_skip "$file" && continue
        git add "$file" 2>/dev/null || true
        ;;
    esac
  done < <(git ls-files --others --exclude-standard)
}

stage_project_paths

git restore --staged .cursor/debug*.log .cursor/*.log 2>/dev/null || true

if git diff --cached --quiet; then
  # Nothing to commit — still push in case we only pulled.
  git push origin HEAD 2>/dev/null || true
  exit 0
fi

SOURCE="local"
if [[ -n "${CURSOR_AGENT:-}" || -n "${CURSOR_CLOUD:-}" ]]; then
  SOURCE="cloud"
fi

git commit -m "Auto-sync: ${SOURCE} changes ($(date '+%Y-%m-%d %H:%M'))"
git push origin HEAD
