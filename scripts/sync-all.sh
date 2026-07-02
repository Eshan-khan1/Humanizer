#!/usr/bin/env bash
# One command to keep local, cloud, and GitHub in sync.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec bash "$ROOT/scripts/sync-github.sh"
