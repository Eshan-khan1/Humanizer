#!/usr/bin/env bash
# Register Thoth Ollama models (grammar + writing).
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
  ollama list 2>/dev/null | awk '{print $1}' | awk -F: '{print $1}' | grep -qx "$1"
}

# Grammar model — prefer fine-tuned 3B, then 7B, then pull a small base model
GRAMMAR_3B_MODEFILE="$ROOT/models/thoth-3b/gguf/Modelfile"
GRAMMAR_MODEFILE="$ROOT/models/thoth-grammar/gguf/Modelfile"
if [[ -f "$GRAMMAR_3B_MODEFILE" ]]; then
  echo "==> Creating thoth-grammar from fine-tuned 3B Modelfile..."
  (cd "$ROOT/models/thoth-3b/gguf" && ollama create thoth-grammar -f Modelfile)
  (cd "$ROOT/models/thoth-3b/gguf" && ollama create thoth-writing -f Modelfile.writing)
elif [[ -f "$GRAMMAR_MODEFILE" ]]; then
  echo "==> Creating thoth-grammar from local Modelfile..."
  ollama create thoth-grammar -f "$GRAMMAR_MODEFILE" 2>/dev/null || ollama create thoth-grammar -f "$GRAMMAR_MODEFILE"
elif has_model thoth-grammar; then
  echo "==> thoth-grammar already installed"
else
  echo "==> Pulling base model for grammar (qwen2.5:0.5b)..."
  ollama pull qwen2.5:0.5b
  ollama cp qwen2.5:0.5b thoth-grammar 2>/dev/null || true
fi

# Writing model — for rewrite/generate
WRITING_MODEFILE="$ROOT/models/thoth-writing/Modelfile"
if [[ -f "$WRITING_MODEFILE" ]]; then
  echo "==> Creating thoth-writing from local Modelfile..."
  ollama create thoth-writing -f "$WRITING_MODEFILE"
elif has_model thoth-writing; then
  echo "==> thoth-writing already installed"
else
  echo "==> Pulling base model for writing (qwen2.5:3b-instruct)..."
  ollama pull qwen2.5:3b-instruct
  ollama cp qwen2.5:3b-instruct thoth-writing 2>/dev/null || true
fi

# One-time alias from previous Humanizer model names.
if has_model humanizer-grammar && ! has_model thoth-grammar; then
  echo "==> Copying humanizer-grammar → thoth-grammar"
  ollama cp humanizer-grammar thoth-grammar 2>/dev/null || true
fi
if has_model humanizer-writing && ! has_model thoth-writing; then
  echo "==> Copying humanizer-writing → thoth-writing"
  ollama cp humanizer-writing thoth-writing 2>/dev/null || true
fi

echo ""
echo "Installed models:"
ollama list | head -20
echo ""
echo "Done. Start the server with: ./start_server.sh"
