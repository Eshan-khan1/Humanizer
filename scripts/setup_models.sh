#!/usr/bin/env bash
# Register Humanizer Ollama models (grammar + writing).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if ! command -v ollama >/dev/null 2>&1; then
  echo "Error: Install Ollama from https://ollama.com"
  exit 1
fi

if ! curl -sf http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
  echo "Error: Ollama is not running. Open the Ollama app and try again."
  exit 1
fi

has_model() {
  ollama list 2>/dev/null | awk '{print $1}' | grep -qx "$1"
}

# Grammar model — use local Modelfile if bundled, else pull a small base model
GRAMMAR_MODEFILE="$ROOT/models/humanizer-grammar/gguf/Modelfile"
if [[ -f "$GRAMMAR_MODEFILE" ]]; then
  echo "==> Creating humanizer-grammar from local Modelfile..."
  ollama create humanizer-grammar -f "$GRAMMAR_MODEFILE" 2>/dev/null || ollama create humanizer-grammar -f "$GRAMMAR_MODEFILE"
elif has_model humanizer-grammar; then
  echo "==> humanizer-grammar already installed"
else
  echo "==> Pulling base model for grammar (qwen2.5:0.5b)..."
  ollama pull qwen2.5:0.5b
  ollama cp qwen2.5:0.5b humanizer-grammar 2>/dev/null || true
fi

# Writing model — for rewrite/generate
WRITING_MODEFILE="$ROOT/models/humanizer-writing/Modelfile"
if [[ -f "$WRITING_MODEFILE" ]]; then
  echo "==> Creating humanizer-writing from local Modelfile..."
  ollama create humanizer-writing -f "$WRITING_MODEFILE"
elif has_model humanizer-writing; then
  echo "==> humanizer-writing already installed"
else
  echo "==> Pulling base model for writing (qwen2.5:3b)..."
  ollama pull qwen2.5:3b
  ollama cp qwen2.5:3b humanizer-writing 2>/dev/null || true
fi

echo ""
echo "Installed models:"
ollama list | head -20
echo ""
echo "Done. Start the server with: ./start_server.sh"
