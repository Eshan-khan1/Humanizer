#!/usr/bin/env bash
# One-time Humanizer setup — Python env, dependencies, Ollama models.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "==> Humanizer installer"
echo ""

# --- Python ---
if ! command -v python3 >/dev/null 2>&1; then
  echo "Error: Python 3 is required. Install from https://www.python.org/downloads/"
  exit 1
fi

PY_VER="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
PY_MAJOR="$(echo "$PY_VER" | cut -d. -f1)"
PY_MINOR="$(echo "$PY_VER" | cut -d. -f2)"
if [[ "$PY_MAJOR" -lt 3 ]] || [[ "$PY_MAJOR" -eq 3 && "$PY_MINOR" -lt 10 ]]; then
  echo "Warning: Python 3.10+ recommended (found $PY_VER)"
fi

echo "==> Creating virtual environment..."
if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

echo "==> Installing Python packages..."
pip install --upgrade pip -q
pip install -r requirements.txt -q

echo "==> Downloading NLTK data..."
python3 -c "
import nltk
for pkg in ('punkt', 'punkt_tab', 'averaged_perceptron_tagger', 'averaged_perceptron_tagger_eng'):
    try:
        nltk.download(pkg, quiet=True)
    except Exception:
        pass
" 2>/dev/null || true

# --- Java (LanguageTool) ---
if ! command -v java >/dev/null 2>&1; then
  echo ""
  echo "Warning: Java not found. Grammar checks need Java 11+."
  echo "  macOS:  brew install openjdk@17"
  echo "  Ubuntu: sudo apt install openjdk-17-jre"
  echo "  Windows: https://adoptium.net/"
else
  echo "==> Java: $(java -version 2>&1 | head -1)"
fi

# --- Ollama ---
if ! command -v ollama >/dev/null 2>&1; then
  echo ""
  echo "Warning: Ollama not found. Rewrite and Generate need Ollama."
  echo "  Install from https://ollama.com then run: ./scripts/setup_models.sh"
else
  echo "==> Ollama found"
  if curl -sf http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
  echo "==> Setting up Ollama models..."
    bash "$ROOT/scripts/setup_models.sh" || echo "Model setup had warnings — see above."
  else
    echo "  Start Ollama (open the Ollama app), then run: ./scripts/setup_models.sh"
  fi
fi

# --- Git hooks (optional) ---
if [[ -f "$ROOT/scripts/install-git-hooks.sh" ]]; then
  bash "$ROOT/scripts/install-git-hooks.sh" 2>/dev/null || true
fi

echo ""
echo "============================================"
echo "  Install complete!"
echo ""
echo "  Next steps:"
echo "    1. ./start_server.sh"
echo "    2. Chrome → chrome://extensions → Load unpacked → select:"
echo "       $ROOT/extension"
echo ""
echo "  Or use a release zip from GitHub Releases."
echo "============================================"
