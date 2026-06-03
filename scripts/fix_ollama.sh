#!/bin/bash
# Fix broken Homebrew Ollama (missing llama-server binary in formula 0.30.x).
# Replaces the brew formula with the official Ollama app, which bundles llama-server.
set -euo pipefail

echo "=== Fixing Ollama (llama-server binary not found) ==="

# Stop any running Homebrew/manual serve process on 11434
if lsof -i :11434 -t >/dev/null 2>&1; then
  echo "Stopping processes on port 11434…"
  kill $(lsof -t -i :11434) 2>/dev/null || true
  sleep 2
fi

# Remove broken formula install (does not ship llama-server)
if brew list ollama &>/dev/null 2>&1; then
  echo "Uninstalling broken Homebrew formula: ollama…"
  brew uninstall ollama || true
fi
# Legacy formula-only serve may still be running without llama-server
pkill -f "Cellar/ollama/.*/ollama serve" 2>/dev/null || true

# Install official app (includes llama-server and MLX/GGUF support)
if ! brew list --cask ollama-app &>/dev/null 2>&1; then
  echo "Installing official Ollama app (Homebrew cask ollama-app)…"
  brew install --cask ollama-app
else
  echo "Ollama app already installed; reinstalling…"
  brew reinstall --cask ollama-app
fi

# Prefer official CLI on PATH
OLLAMA_BIN="/Applications/Ollama.app/Contents/Resources/ollama"
if [[ -x "$OLLAMA_BIN" ]]; then
  echo "Using: $OLLAMA_BIN"
  export PATH="/Applications/Ollama.app/Contents/Resources:$PATH"
else
  OLLAMA_BIN="$(command -v ollama || true)"
fi

if [[ -z "${OLLAMA_BIN:-}" || ! -x "$OLLAMA_BIN" ]]; then
  echo "Ollama CLI not found. Install manually from https://ollama.com/download" >&2
  exit 1
fi

# Start server (app may auto-start; this ensures API is up)
open -a Ollama 2>/dev/null || true
sleep 3
"$OLLAMA_BIN" serve >/dev/null 2>&1 &
sleep 3

echo "Waiting for API…"
for _ in $(seq 1 30); do
  if curl -sf http://127.0.0.1:11434/api/tags >/dev/null; then
    break
  fi
  sleep 1
done

if ! curl -sf http://127.0.0.1:11434/api/tags >/dev/null; then
  echo "Ollama API did not start. Open the Ollama app from Applications and try again." >&2
  exit 1
fi

echo "Pulling mistral (if needed)…"
"$OLLAMA_BIN" pull mistral || true

echo "Testing /api/generate…"
TEST=$(curl -sf -X POST http://127.0.0.1:11434/api/generate \
  -H "Content-Type: application/json" \
  -d '{"model":"mistral","prompt":"Say OK","stream":false}' 2>&1) || TEST="FAILED: $TEST"

if echo "$TEST" | grep -q '"error".*llama-server'; then
  echo "Generate still failing with llama-server error:" >&2
  echo "$TEST" >&2
  echo "" >&2
  echo "Try the official installer instead:" >&2
  echo "  brew uninstall ollama 2>/dev/null; curl -fsSL https://ollama.com/install.sh | sh" >&2
  exit 1
fi

echo "=== Ollama fixed ==="
echo "$TEST" | head -c 200
echo ""
echo "Add to your shell profile (optional):"
echo '  export PATH="/Applications/Ollama.app/Contents/Resources:$PATH"'
