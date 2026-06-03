#!/bin/bash
# Start the local Humanizer API (grammar + humanize) on http://127.0.0.1:8000
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

VENV="$ROOT/.venv"
PYTHON="$VENV/bin/python"

if [[ ! -d "$VENV" ]]; then
  echo "Virtual environment not found. Run ./run.sh first to set up dependencies." >&2
  exit 1
fi

echo "Installing requirements…"
"$PYTHON" -m pip install -r requirements.txt --quiet

if curl -sf http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
  if ! curl -sf -X POST http://127.0.0.1:11434/api/generate \
      -H "Content-Type: application/json" \
      -d '{"model":"mistral","prompt":"ok","stream":false}' 2>&1 | grep -q '"response"'; then
    echo "WARNING: Ollama API is up but generate fails (llama-server missing)." >&2
    echo "  Fix: ./scripts/fix_ollama.sh" >&2
  fi
else
  echo "NOTE: Ollama not reachable on :11434 — grammar uses LanguageTool only until fixed." >&2
  echo "  Fix: ./scripts/fix_ollama.sh" >&2
fi

echo "Starting Humanizer local server at http://127.0.0.1:8000"
echo "  POST /grammar  — grammar & spelling checks"
echo "  POST /humanize — AI rewrite (requires Ollama + mistral)"
echo ""
exec "$PYTHON" server.py
