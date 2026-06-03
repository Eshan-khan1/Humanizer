#!/bin/bash
# macOS launcher: venv, deps, NLTK data, then run the PyWebView app.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

export NLTK_DATA="$ROOT/nltk_data"
mkdir -p "$NLTK_DATA"

VENV="$ROOT/.venv"
PYTHON="$VENV/bin/python"

if ! command -v python3 &>/dev/null; then
  echo "python3 not found. Install Python 3 from python.org or Homebrew." >&2
  exit 1
fi

if [[ ! -d "$VENV" ]]; then
  echo "Creating virtual environment…"
  python3 -m venv "$VENV"
fi

echo "Using: $PYTHON"
"$PYTHON" -m pip install --upgrade pip --quiet
echo "Installing requirements…"
"$PYTHON" -m pip install -r requirements.txt

echo "Verifying PyWebView…"
"$PYTHON" - <<'PY'
import sys
import webview
print(f"  Python {sys.version.split()[0]}")
print(f"  pywebview {webview.__version__ if hasattr(webview, '__version__') else 'installed'}")
PY

echo "Downloading NLTK punkt data…"
"$PYTHON" - <<'PY'
import nltk

for resource in ("punkt", "punkt_tab"):
    try:
        nltk.data.find(f"tokenizers/{resource}")
        print(f"  {resource}: already present")
    except LookupError:
        print(f"  {resource}: downloading…")
        nltk.download(resource, quiet=True)
PY

echo "Starting Humanize (PyWebView)…"
exec "$PYTHON" main.py
