#!/bin/bash
# Start the local Thoth API (grammar + humanize) on http://127.0.0.1:8000
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

# Stay in sync with GitHub before starting the server.
bash "$ROOT/scripts/pull-github.sh" 2>/dev/null || true

# shellcheck source=scripts/ollama_gpu_env.sh
source "$ROOT/scripts/ollama_gpu_env.sh"

VENV="$ROOT/.venv"
PYTHON="$VENV/bin/python"
THOTH_PORT=8000

if [[ ! -d "$VENV" ]]; then
  echo "Virtual environment not found. Run ./run.sh first to set up dependencies." >&2
  exit 1
fi

echo "Installing requirements..."
"$PYTHON" -m pip install -r requirements.txt --quiet

ollama_configure_gpu
ollama_ensure_serve

if curl -sf http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
  if ! curl -sf -X POST http://127.0.0.1:11434/api/generate \
      -H "Content-Type: application/json" \
      -d '{"model":"thoth-grammar","prompt":"ok","stream":false}' 2>&1 | grep -q '"response"'; then
    echo "WARNING: Ollama API is up but generate fails (llama-server missing)." >&2
    echo "  Fix: ./scripts/fix_ollama.sh" >&2
  fi
else
  echo "NOTE: Ollama not reachable on :11434 - grammar uses LanguageTool only until fixed." >&2
  echo "  Fix: ./scripts/fix_ollama.sh" >&2
fi

if command -v lsof >/dev/null 2>&1 && lsof -ti:"${THOTH_PORT}" >/dev/null 2>&1; then
  echo "Stopping previous server on port ${THOTH_PORT}..."
  lsof -ti:"${THOTH_PORT}" | xargs kill -15 2>/dev/null || true
  sleep 2
  if lsof -ti:"${THOTH_PORT}" >/dev/null 2>&1; then
    lsof -ti:"${THOTH_PORT}" | xargs kill -9 2>/dev/null || true
    sleep 1
  fi
fi

echo "Starting Thoth local server at http://127.0.0.1:${THOTH_PORT}"
echo "  POST /grammar?quick=true - fast underlines (LanguageTool)"
echo "  POST /grammar/quick      - same fast check"
echo "  POST /grammar            - full check (Agent1: LT, Agent2: deep rewrite)"
echo "  POST /humanize           - AI rewrite (requires Ollama + thoth-grammar)"
echo "  POST /rewrite            - Writing Agent: tone rewrite"
echo "  POST /generate           - Writing Agent: expand to email or essay"
echo "  Grammar model: ${OLLAMA_GRAMMAR_MODEL:-thoth-grammar}"
echo "  Writing model: ${OLLAMA_WRITING_MODEL:-thoth-writing}"
echo "  Security: localhost-only, rate-limited, optional Bearer auth"
echo "    Set THOTH_REQUIRE_AUTH=1 to require a token (printed on startup)"
echo "    Or set THOTH_API_TOKEN yourself and paste it in extension Settings"
echo ""
# Pass Ollama GPU env through to server.py (and any ollama serve it spawns).
export OLLAMA_GPU_MEMORY_FRACTION OLLAMA_GPU_OVERHEAD OLLAMA_FLASH_ATTENTION OLLAMA_LLM_LIBRARY OLLAMA_KEEP_ALIVE
exec "$PYTHON" server.py
