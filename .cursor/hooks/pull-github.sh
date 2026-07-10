#!/usr/bin/env bash
# Cursor subagentStart hook — pull latest from GitHub before work begins.
cat >/dev/null
exec "$(git rev-parse --show-toplevel)/scripts/pull-github.sh"
