#!/usr/bin/env bash
# Fetch and merge the latest code from GitHub (cloud → local / agent workspace).
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0
cd "$ROOT"

if [[ -n "$(git status --porcelain 2>/dev/null)" ]]; then
  # Stash uncommitted work so pull can proceed; restore after.
  STASHED=0
  if git stash push -u -m "pull-github-auto-$(date +%s)" >/dev/null 2>&1; then
    STASHED=1
  fi
else
  STASHED=0
fi

git fetch origin --prune

BRANCH="$(git branch --show-current 2>/dev/null || echo main)"
DEFAULT_BRANCH="$(git remote show origin 2>/dev/null | awk '/HEAD branch/ {print $NF}' || echo main)"
DEFAULT_BRANCH="${DEFAULT_BRANCH:-main}"

if [[ "$BRANCH" == "$DEFAULT_BRANCH" ]]; then
  git pull --ff-only origin "$DEFAULT_BRANCH" 2>/dev/null || \
    git pull --rebase origin "$DEFAULT_BRANCH" 2>/dev/null || true
else
  # Feature branch: update the branch, then rebase onto latest main when possible.
  git pull --rebase origin "$BRANCH" 2>/dev/null || true
  if git show-ref --verify --quiet "refs/remotes/origin/$DEFAULT_BRANCH"; then
    git rebase "origin/$DEFAULT_BRANCH" 2>/dev/null || git rebase --abort 2>/dev/null || true
  fi
fi

if [[ "$STASHED" -eq 1 ]]; then
  git stash pop >/dev/null 2>&1 || true
fi
