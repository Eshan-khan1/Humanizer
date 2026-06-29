#!/usr/bin/env bash
# Cursor stop hook — sync repo to GitHub after agent finishes.
cat >/dev/null
exec "$(git rev-parse --show-toplevel)/scripts/sync-github.sh"
