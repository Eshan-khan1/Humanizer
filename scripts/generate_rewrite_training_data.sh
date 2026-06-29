#!/usr/bin/env bash
# Step 1: generate tone-rewrite training data via Groq API (matches grammar count).
#
#   export GROQ_API_KEY=your_key_here
#   ./scripts/generate_rewrite_training_data.sh
#
# Then merge + train:
#   .venv/bin/python prepare_data.py --skip-c4
#   .venv/bin/python scripts/finetune_grammar_lora.py

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PYTHON="${ROOT}/.venv/bin/python"
if [[ ! -x "$PYTHON" ]]; then
  PYTHON=python3
fi

if [[ -z "${GROQ_API_KEY:-}" ]]; then
  echo "Set your Groq API key first:"
  echo "  export GROQ_API_KEY=your_key_here"
  exit 1
fi

if [[ ! -f train_data.jsonl ]]; then
  echo "Building grammar data first …"
  "$PYTHON" prepare_data.py --skip-c4
fi

echo "Generating tone rewrite data via Groq API …"
"$PYTHON" "Generate tone data.py" --match-grammar --skip-tone-check

echo ""
echo "Done. Next:"
echo "  $PYTHON prepare_data.py --skip-c4"
echo "  $PYTHON scripts/finetune_grammar_lora.py --prepare-only"
echo "  $PYTHON scripts/finetune_grammar_lora.py --skip-export"
