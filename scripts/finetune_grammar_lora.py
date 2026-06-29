#!/usr/bin/env python3
"""
Fine-tune Qwen2.5-7B-Instruct for grammar correction with MLX LoRA.

Steps:
  1. prepare_data.py → train_data.jsonl / val_data.jsonl (task, input, output)
  2. Convert to mlx_lm chat JSONL and LoRA fine-tune on Apple Silicon
  3. Fuse adapters, convert to GGUF for Ollama, write Modelfile

Usage:
  pip install -r requirements-finetune.txt
  .venv/bin/python prepare_data.py          # build train_data.jsonl / val_data.jsonl
  .venv/bin/python scripts/finetune_grammar_lora.py --prepare-only
  .venv/bin/python scripts/finetune_grammar_lora.py --skip-export

Optional for GGUF export (Qwen2.5 is not supported by mlx_lm --export-gguf):
  git clone https://github.com/ggml-org/llama.cpp
  cd llama.cpp && cmake -B build && cmake --build build --config Release
  export LLAMA_CPP_PATH=/path/to/llama.cpp

After export:
  cd models/humanizer-grammar/gguf
  ollama create humanizer-grammar -f ../Modelfile
  OLLAMA_MODEL=humanizer-grammar ./start_server.sh
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import shutil
import subprocess
import sys
import types
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
RULES_PATH = ROOT / "grammar_rules.json"
TEST_DATA = ROOT / "test_data"
FINETUNE_DATA_PATH = TEST_DATA / "finetune_pairs.json"
TRAIN_DATA_PATH = ROOT / "train_data.jsonl"
VAL_DATA_PATH = ROOT / "val_data.jsonl"
MLX_DATA_DIR = TEST_DATA / "mlx_lora"
OUTPUT_DIR = ROOT / "models" / "humanizer-grammar"
LORA_DIR = OUTPUT_DIR / "lora"
MERGED_DIR = OUTPUT_DIR / "merged"
GGUF_DIR = OUTPUT_DIR / "gguf"

PAIR_FILES = (
    TEST_DATA / "pairs.json",
    TEST_DATA / "jfleg_pairs.json",
    TEST_DATA / "synthetic_pairs.json",
)

# 4-bit MLX weights → QLoRA (fits ~16–32 GB unified memory).
BASE_MODEL = "mlx-community/Qwen2.5-7B-Instruct-4bit"
OLLAMA_MODEL_NAME = "humanizer-grammar"
OLLAMA_WRITING_MODEL_NAME = "humanizer-writing"

DEEP_FIX_RULES = """Fix grammar errors. Rules:
- Irregular verbs: buy→bought, go→went, see→saw, run→ran
- "i" alone always→"I"
- "me and him"→"He and I", "me and her"→"She and I" as ONE phrase
- Past tense: "we was"→"we were", "he were"→"he was", "they was"→"they were"
- "have seen yesterday"→"saw yesterday" — never use perfect tense with past time words (yesterday, last week, ago)
- "don't have no"→"don't have any", never drop the verb
- "their" before a noun is ALWAYS correct, never change to "they're" or "there"
- "they're" means "they are" — only use before a verb
- NEVER change a word that was already correctly fixed
- NEVER change prepositions (about, with, while, for, of)
- No space before punctuation, never split sentences, never add commas unnecessarily
- Return ONLY the corrected sentence, nothing else

Examples:
me and him was going → He and I were going
i seen him yesterday → I saw him yesterday
we was talking → we were talking
she have went yesterday → she went yesterday
i don't have no money → I don't have any money
their new house → their new house (no change, already correct)
they're going → they're going (no change, already correct)"""

# Compact prompt for LoRA training (must fit in max_seq_length=256 with input+output).
# Full DEEP_FIX_RULES is still used at inference in server.py / Ollama Modelfile.
TRAIN_GRAMMAR_PREFIX = (
    "Fix grammar errors. Return only the corrected sentence.\n\nCorrect this:\n\n"
)

TRAIN_GRAMMAR_SYSTEM = (
    "Fix grammar and spelling with minimal, safe edits. Return only the corrected sentence."
)

TRAIN_TONE_SYSTEM = (
    "Rewrite text to match the requested tone. Make bold changes to word choice, "
    "structure, and length as needed. Return only the full rewritten text."
)

TONE_REWRITE_FLEXIBILITY = (
    " You can change word choice, structure, and length as needed to fully achieve this tone."
)

TASK_USER_PREFIX = {
    "grammar": None,  # uses build_user_prompt()
    "rewrite_professional": (
        "Rewrite the following text in a professional, formal tone. "
        "Return only the rewritten text.\n\n"
    ),
    "rewrite_casual": (
        "Rewrite the following text in a casual, natural tone. "
        "Return only the rewritten text.\n\n"
    ),
    "rewrite_concise": (
        "Rewrite the following text to be more concise. "
        "Return only the rewritten text.\n\n"
    ),
}


def log(message: str) -> None:
    print(message, flush=True)


def load_json_list(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8") as handle:
        raw = json.load(handle)
    if isinstance(raw, dict):
        entries = raw.get("pairs", [])
    elif isinstance(raw, list):
        entries = raw
    else:
        return []
    return [entry for entry in entries if isinstance(entry, dict)]


def _sentence_like(text: str) -> bool:
    text = text.strip()
    if not text:
        return False
    if any(text.endswith(p) for p in ".!?"):
        return True
    return len(text.split()) >= 3


def example_to_pair(wrong: str, correct: str, triggers: list[str]) -> tuple[str, str] | None:
    wrong = wrong.strip()
    correct = correct.strip()
    if not wrong or not correct or wrong.lower() == correct.lower():
        return None

    if _sentence_like(wrong) and _sentence_like(correct):
        return wrong, correct

    if " " in wrong and " " in correct:
        return wrong, correct

    multi_triggers = [t for t in triggers if " " in t and wrong.lower() in t.lower()]
    if multi_triggers:
        template = multi_triggers[0]
        if wrong.lower() in template.lower():
            mapped = re.sub(
                re.escape(wrong),
                correct,
                template,
                count=1,
                flags=re.IGNORECASE,
            )
            if mapped.lower() != template.lower():
                return template, mapped

    return f"I think {wrong} is wrong.", f"I think {correct} is correct."


def pairs_from_grammar_rules(path: Path = RULES_PATH) -> list[dict[str, Any]]:
    log(f"Converting rules from {path} …")
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)

    rules = data.get("rules", [])
    pairs: list[dict[str, Any]] = []
    seen: set[str] = set()

    for rule in rules:
        if not isinstance(rule, dict):
            continue
        triggers = [str(t).strip() for t in rule.get("triggers") or [] if str(t).strip()]
        rule_id = str(rule.get("id") or "")

        for example in rule.get("examples") or []:
            if not isinstance(example, dict):
                continue
            wrong = str(example.get("wrong") or "").strip()
            correct = str(example.get("correct") or "").strip()
            converted = example_to_pair(wrong, correct, triggers)
            if not converted:
                continue
            w, c = converted
            key = w.lower()
            if key in seen or w == c:
                continue
            seen.add(key)
            pairs.append(
                {
                    "wrong": w,
                    "correct": c,
                    "errors": [],
                    "source": "grammar_rules",
                    "rule_id": rule_id,
                }
            )

    log(f"  grammar_rules.json → {len(pairs)} pairs")
    return pairs


def merge_training_pairs() -> list[dict[str, Any]]:
    log("=" * 60)
    log("Step 1 — Build fine-tune dataset")
    log("=" * 60)

    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    counts: dict[str, int] = {}

    sources: list[tuple[str, list[dict[str, Any]]]] = []

    for path in PAIR_FILES:
        items = load_json_list(path)
        sources.append((path.name, items))

    sources.append(("grammar_rules.json", pairs_from_grammar_rules()))

    filtered = 0
    duplicates = 0

    for label, items in sources:
        added = 0
        for item in items:
            wrong = str(item.get("wrong") or "").strip()
            correct = str(item.get("correct") or "").strip()
            if not wrong or not correct or wrong == correct:
                filtered += 1
                continue
            if len(wrong) <= 5 or len(wrong) >= 500:
                filtered += 1
                continue
            key = wrong.lower()
            if key in seen:
                duplicates += 1
                continue
            seen.add(key)
            entry = {
                "wrong": wrong,
                "correct": correct,
                "errors": item.get("errors") or [],
                "source": item.get("source") or label,
            }
            if item.get("rule_id"):
                entry["rule_id"] = item["rule_id"]
            merged.append(entry)
            added += 1
        counts[label] = added
        log(f"  {label}: +{added}")

    FINETUNE_DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    with FINETUNE_DATA_PATH.open("w", encoding="utf-8") as handle:
        json.dump(merged, handle, indent=2, ensure_ascii=False)
        handle.write("\n")

    log(f"Filtered: {filtered}, duplicates skipped: {duplicates}")
    log(f"Total training pairs: {len(merged)} → {FINETUNE_DATA_PATH}")
    return merged


def build_user_prompt(wrong: str) -> str:
    return f"{DEEP_FIX_RULES}\n\nCorrect this:\n\n{wrong}"


def build_user_prompt_for_task(
    task: str, input_text: str, *, instruction: str = ""
) -> str:
    if task == "grammar":
        return build_user_prompt(input_text)
    if task == "rewrite_tone":
        if instruction:
            return f"{instruction}\n\n{input_text}"
        return input_text
    prefix = TASK_USER_PREFIX.get(task)
    if prefix:
        return f"{prefix}{input_text}"
    return build_user_prompt(input_text)


def build_train_user_prompt_for_task(
    task: str, input_text: str, *, instruction: str = ""
) -> str:
    if task == "grammar":
        return f"{TRAIN_GRAMMAR_PREFIX}{input_text}"
    if task == "rewrite_tone":
        if instruction:
            inst = instruction.strip()
            lower = inst.lower()
            if "change word choice" not in lower and "restructure" not in lower:
                if not inst.endswith((".", "!", "?")):
                    inst += "."
                inst += TONE_REWRITE_FLEXIBILITY
            return f"{inst}\n\n{input_text}"
        return input_text
    prefix = TASK_USER_PREFIX.get(task)
    if prefix:
        return f"{prefix}{input_text}"
    return f"{TRAIN_GRAMMAR_PREFIX}{input_text}"


def _system_prompt_for_task(task: str) -> str:
    if task == "rewrite_tone":
        return TRAIN_TONE_SYSTEM
    return TRAIN_GRAMMAR_SYSTEM


def _tone_repeat_count(
    tone_rows: int,
    other_rows: int,
    *,
    target_fraction: float,
) -> int:
    if tone_rows <= 0 or target_fraction <= 0:
        return 1
    if target_fraction >= 1.0:
        return max(1, int(other_rows / max(tone_rows, 1)) + 1)
    # Solve: tone*repeat / (other + tone*repeat) = target_fraction
    numerator = target_fraction * other_rows
    denominator = tone_rows * (1.0 - target_fraction)
    if denominator <= 0:
        return 1
    return max(1, int(round(numerator / denominator)))


def _load_train_tokenizer() -> Any:
    from mlx_lm import load

    _, tokenizer = load(BASE_MODEL)
    return tokenizer


def _chat_token_count(tokenizer: Any, messages: list[dict[str, str]]) -> int:
    text = tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=False,
    )
    return len(tokenizer.encode(text))


def _jsonl_record_to_chat(
    row: dict[str, Any],
    *,
    for_training: bool = True,
) -> dict[str, list[dict[str, str]]] | None:
    task = str(row.get("task") or "grammar").strip()
    input_text = str(row.get("input") or row.get("wrong") or "").strip()
    output_text = str(row.get("output") or row.get("correct") or "").strip()
    instruction = str(row.get("instruction") or "").strip()
    if not input_text or not output_text or input_text == output_text:
        return None
    build_prompt = build_train_user_prompt_for_task if for_training else build_user_prompt_for_task
    messages: list[dict[str, str]] = []
    if for_training:
        messages.append({"role": "system", "content": _system_prompt_for_task(task)})
    messages.extend(
        [
            {
                "role": "user",
                "content": build_prompt(task, input_text, instruction=instruction),
            },
            {"role": "assistant", "content": output_text},
        ]
    )
    return {"messages": messages}


def convert_jsonl_to_mlx_chat(
    src: Path,
    dest: Path,
    *,
    max_seq_length: int = 384,
    tokenizer: Any | None = None,
    tone_target_fraction: float = 0.0,
) -> tuple[int, int]:
    """Stream JSONL task/input/output (or wrong/correct) → mlx_lm chat JSONL."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    tone_rows = 0
    other_rows = 0
    with src.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            rows.append(row)
            if str(row.get("task") or "grammar") == "rewrite_tone":
                tone_rows += 1
            else:
                other_rows += 1

    tone_repeat = 1
    if tone_target_fraction > 0 and tone_rows > 0:
        tone_repeat = _tone_repeat_count(
            tone_rows,
            other_rows,
            target_fraction=tone_target_fraction,
        )
        log(
            f"  Upsampling rewrite_tone {tone_repeat}x "
            f"({tone_rows:,} → {tone_rows * tone_repeat:,}, "
            f"target {100 * tone_target_fraction:.0f}% of batches)"
        )

    count = 0
    skipped = 0
    with dest.open("w", encoding="utf-8") as out:
        for row in rows:
            task = str(row.get("task") or "grammar")
            repeats = tone_repeat if task == "rewrite_tone" else 1
            for _ in range(repeats):
                chat = _jsonl_record_to_chat(row, for_training=True)
                if not chat:
                    continue
                if tokenizer is not None:
                    token_count = _chat_token_count(tokenizer, chat["messages"])
                    if token_count > max_seq_length:
                        skipped += 1
                        continue
                out.write(json.dumps(chat, ensure_ascii=False) + "\n")
                count += 1
    return count, skipped


def prepare_mlx_from_prepared_data(
    *,
    max_seq_length: int = 384,
    tone_target_fraction: float = 0.35,
) -> tuple[Path, int]:
    """Convert train_data.jsonl / val_data.jsonl → mlx_lm data directory."""
    if not TRAIN_DATA_PATH.is_file():
        log(f"ERROR: Missing {TRAIN_DATA_PATH}")
        log("Run: .venv/bin/python prepare_data.py")
        raise SystemExit(1)

    log("=" * 60)
    log("Step 1 — Convert prepared JSONL to MLX chat format")
    log("=" * 60)
    log(f"Using compact training prompts (max_seq_length={max_seq_length}) …")

    log("Loading tokenizer for length filtering …")
    tokenizer = _load_train_tokenizer()

    train_path = MLX_DATA_DIR / "train.jsonl"
    valid_path = MLX_DATA_DIR / "valid.jsonl"

    train_count, train_skipped = convert_jsonl_to_mlx_chat(
        TRAIN_DATA_PATH,
        train_path,
        max_seq_length=max_seq_length,
        tokenizer=tokenizer,
        tone_target_fraction=tone_target_fraction,
    )
    if VAL_DATA_PATH.is_file():
        valid_count, valid_skipped = convert_jsonl_to_mlx_chat(
            VAL_DATA_PATH,
            valid_path,
            max_seq_length=max_seq_length,
            tokenizer=tokenizer,
            tone_target_fraction=0.0,
        )
    else:
        log(f"WARNING: {VAL_DATA_PATH} not found; reusing 10% of train for valid")
        valid_count = 0
        valid_skipped = 0

    if train_skipped or valid_skipped:
        log(
            f"Skipped {train_skipped + valid_skipped:,} examples longer than "
            f"{max_seq_length} tokens"
        )

    if train_count == 0:
        log("ERROR: No training examples fit within max_seq_length")
        raise SystemExit(1)

    if valid_count == 0:
        lines = train_path.read_text(encoding="utf-8").splitlines()
        random.seed(3407)
        random.shuffle(lines)
        split_at = max(1, int(len(lines) * 0.9))
        train_path.write_text("\n".join(lines[:split_at]) + "\n", encoding="utf-8")
        valid_path.write_text("\n".join(lines[split_at:]) + "\n", encoding="utf-8")
        train_count = split_at
        valid_count = len(lines) - split_at

    log(f"MLX data: {train_count} train, {valid_count} valid → {MLX_DATA_DIR}")
    return MLX_DATA_DIR, train_count


def write_mlx_jsonl(
    pairs: list[dict[str, Any]],
    *,
    valid_fraction: float = 0.05,
    max_seq_length: int = 256,
) -> Path:
    """Write train.jsonl / valid.jsonl in mlx_lm chat format."""
    MLX_DATA_DIR.mkdir(parents=True, exist_ok=True)
    train_path = MLX_DATA_DIR / "train.jsonl"
    valid_path = MLX_DATA_DIR / "valid.jsonl"

    log("Loading tokenizer for length filtering …")
    tokenizer = _load_train_tokenizer()

    shuffled = list(pairs)
    random.seed(3407)
    random.shuffle(shuffled)

    filtered: list[dict[str, Any]] = []
    skipped = 0

    for pair in shuffled:
        chat = _jsonl_record_to_chat(
            {"wrong": pair["wrong"], "correct": pair["correct"], "task": "grammar"},
            for_training=True,
        )
        if not chat:
            continue
        if _chat_token_count(tokenizer, chat["messages"]) > max_seq_length:
            skipped += 1
            continue
        filtered.append(pair)

    split_at = max(1, int(len(filtered) * (1.0 - valid_fraction)))
    train_pairs = filtered[:split_at]
    valid_pairs = filtered[split_at:] or filtered[-max(1, len(filtered) // 20) :]

    if skipped:
        log(f"Skipped {skipped:,} legacy pairs longer than {max_seq_length} tokens")

    def to_chat_line(wrong: str, correct: str) -> str:
        chat = _jsonl_record_to_chat(
            {"wrong": wrong, "correct": correct, "task": "grammar"},
            for_training=True,
        )
        assert chat is not None
        return json.dumps(chat, ensure_ascii=False)

    with train_path.open("w", encoding="utf-8") as handle:
        for pair in train_pairs:
            handle.write(to_chat_line(pair["wrong"], pair["correct"]) + "\n")

    with valid_path.open("w", encoding="utf-8") as handle:
        for pair in valid_pairs:
            handle.write(to_chat_line(pair["wrong"], pair["correct"]) + "\n")

    log(f"MLX data: {len(train_pairs)} train, {len(valid_pairs)} valid → {MLX_DATA_DIR}")
    return MLX_DATA_DIR


def train_with_mlx(
    *,
    pairs: list[dict[str, Any]] | None = None,
    data_dir: Path | None = None,
    num_examples: int = 0,
    iters: int,
    max_seq_length: int,
    lora_rank: int,
    learning_rate: float,
    batch_size: int,
    num_layers: int,
    grad_accumulation_steps: int,
) -> None:
    log("=" * 60)
    log("Step 2 — LoRA fine-tune with MLX")
    log("=" * 60)

    try:
        import mlx.core as mx
        from mlx_lm.lora import run as mlx_lora_run
    except ImportError as exc:
        log("ERROR: Install fine-tune deps: pip install -r requirements-finetune.txt")
        raise SystemExit(1) from exc

    if "gpu" not in str(mx.default_device()).lower():
        log(
            "WARNING: MLX GPU not detected. Training may be slow or fail. "
            "Run on Apple Silicon with mlx installed."
        )

    data_dir = data_dir or write_mlx_jsonl(pairs or [], max_seq_length=max_seq_length)
    if num_examples <= 0:
        num_examples = len(pairs) if pairs else 0
    if num_examples <= 0:
        log("ERROR: No training examples")
        raise SystemExit(1)
    LORA_DIR.mkdir(parents=True, exist_ok=True)

    args = types.SimpleNamespace(
        model=BASE_MODEL,
        train=True,
        test=False,
        data=str(data_dir),
        fine_tune_type="lora",
        optimizer="adam",
        optimizer_config={
            "adam": {},
            "adamw": {},
            "muon": {},
            "sgd": {},
            "adafactor": {},
        },
        seed=3407,
        num_layers=num_layers,
        batch_size=batch_size,
        iters=iters,
        val_batches=25,
        learning_rate=learning_rate,
        steps_per_report=10,
        steps_per_eval=max(iters // 4, 50),
        resume_adapter_file=None,
        adapter_path=str(LORA_DIR),
        save_every=max(iters // 2, 50),
        test_batches=100,
        max_seq_length=max_seq_length,
        config=None,
        grad_checkpoint=True,
        grad_accumulation_steps=grad_accumulation_steps,
        clear_cache_threshold=0,
        lr_schedule=None,
        lora_parameters={"rank": lora_rank, "dropout": 0.0, "scale": float(lora_rank)},
        mask_prompt=True,
        report_to=None,
        project_name=None,
        trust_remote_code=False,
    )

    log(f"Base model: {BASE_MODEL}")
    log(
        f"Training {iters} iters on {num_examples} examples "
        f"(batch={batch_size}, grad_accum={grad_accumulation_steps}, "
        f"layers={num_layers}, rank={lora_rank}) …"
    )
    mlx_lora_run(args)
    log(f"LoRA adapter saved → {LORA_DIR}")


def _find_llama_cpp() -> Path | None:
    env_path = os.environ.get("LLAMA_CPP_PATH", "").strip()
    if env_path:
        candidate = Path(env_path).expanduser().resolve()
        if (candidate / "convert_hf_to_gguf.py").is_file():
            return candidate

    for candidate in (ROOT / "llama.cpp", Path.home() / "llama.cpp"):
        if (candidate / "convert_hf_to_gguf.py").is_file():
            return candidate.resolve()
    return None


def _find_llama_quantize(llama_cpp: Path) -> Path | None:
    for rel in (
        "build/bin/llama-quantize",
        "build/Release/llama-quantize",
        "build/llama-quantize",
        "llama-quantize",
    ):
        candidate = llama_cpp / rel
        if candidate.is_file():
            return candidate
    return shutil.which("llama-quantize") and Path(shutil.which("llama-quantize"))  # type: ignore[arg-type]


def fuse_adapters() -> None:
    log("Fusing LoRA adapters into base weights …")
    MERGED_DIR.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable,
        "-m",
        "mlx_lm",
        "fuse",
        "--model",
        BASE_MODEL,
        "--adapter-path",
        str(LORA_DIR),
        "--save-path",
        str(MERGED_DIR),
        "--dequantize",
    ]
    subprocess.run(cmd, check=True)
    log(f"Fused model saved → {MERGED_DIR}")


def convert_to_gguf(quantization: str) -> Path:
    llama_cpp = _find_llama_cpp()
    if llama_cpp is None:
        log(
            "ERROR: llama.cpp not found. Clone and build it, then set LLAMA_CPP_PATH:\n"
            "  git clone https://github.com/ggml-org/llama.cpp\n"
            "  cd llama.cpp && cmake -B build && cmake --build build --config Release\n"
            "  export LLAMA_CPP_PATH=$PWD\n"
            "Then re-run with --export-only"
        )
        raise SystemExit(1)

    GGUF_DIR.mkdir(parents=True, exist_ok=True)
    f16_path = GGUF_DIR / "humanizer-grammar-f16.gguf"

    convert_script = llama_cpp / "convert_hf_to_gguf.py"
    log(f"Converting fused model to GGUF (f16) via {convert_script} …")
    subprocess.run(
        [
            sys.executable,
            str(convert_script),
            str(MERGED_DIR),
            "--outfile",
            str(f16_path),
            "--outtype",
            "f16",
        ],
        check=True,
    )

    if quantization in ("f16", "fp16"):
        return f16_path

    quantize_bin = _find_llama_quantize(llama_cpp)
    if quantize_bin is None:
        log(
            f"WARNING: llama-quantize not found; keeping f16 GGUF. "
            f"Build llama.cpp to quantize to {quantization}."
        )
        return f16_path

    out_path = GGUF_DIR / f"humanizer-grammar-{quantization}.gguf"
    log(f"Quantizing → {out_path} ({quantization}) …")
    subprocess.run(
        [str(quantize_bin), str(f16_path), str(out_path), quantization],
        check=True,
    )
    return out_path


def export_for_ollama(quantization: str = "q4_k_m") -> None:
    log("=" * 60)
    log("Step 3 — Export for Ollama")
    log("=" * 60)

    fuse_adapters()
    gguf_path = convert_to_gguf(quantization)

    modelfile_path = GGUF_DIR / "Modelfile"
    modelfile_body = _build_modelfile(gguf_path.name)
    modelfile_path.write_text(modelfile_body, encoding="utf-8")

    writing_modelfile_path = GGUF_DIR / "Modelfile.writing"
    writing_modelfile_body = _build_writing_modelfile(gguf_path.name)
    writing_modelfile_path.write_text(writing_modelfile_body, encoding="utf-8")

    log(f"Wrote {modelfile_path}")
    log(f"Wrote {writing_modelfile_path}")
    log("")
    log("Register in Ollama:")
    log(f"  cd {GGUF_DIR}")
    log(f"  ollama create {OLLAMA_MODEL_NAME} -f Modelfile")
    log(f"  ollama create {OLLAMA_WRITING_MODEL_NAME} -f Modelfile.writing")
    log("")
    log("Then start the server:")
    log(f"  OLLAMA_GRAMMAR_MODEL={OLLAMA_MODEL_NAME} OLLAMA_WRITING_MODEL={OLLAMA_WRITING_MODEL_NAME} ./start_server.sh")


def _build_modelfile(gguf_filename: str) -> str:
    return f"""# Humanizer grammar fine-tune (Qwen2.5-7B-Instruct + MLX LoRA)
# Build: ollama create {OLLAMA_MODEL_NAME} -f Modelfile
# Run from: models/humanizer-grammar/gguf/

FROM ./{gguf_filename}

TEMPLATE \"\"\"{{{{- if .System }}}}<|im_start|>system
{{{{ .System }}}}
{{{{ end }}}}{{{{- if .Prompt }}}}<|im_start|>user
{{{{ .Prompt }}}}
<|im_start|>assistant
{{{{ end }}}}{{{{ .Response }}}}
\"\"\"

SYSTEM \"\"\"You are a grammar correction assistant. Fix grammar and spelling with minimal, safe edits. Return only the corrected sentence.\"\"\"

PARAMETER temperature 0.2
PARAMETER top_p 0.9
PARAMETER num_ctx 4096
PARAMETER stop "<|endoftext|>"
"""


def _build_writing_modelfile(gguf_filename: str) -> str:
    return f"""# Humanizer Writing Agent — Rewrite + Generate (Qwen2.5-7B + MLX LoRA)
# Build: ollama create {OLLAMA_WRITING_MODEL_NAME} -f Modelfile.writing
# Run from: models/humanizer-grammar/gguf/

FROM ./{gguf_filename}

TEMPLATE \"\"\"{{{{- if .System }}}}<|im_start|>system
{{{{ .System }}}}
{{{{ end }}}}{{{{- if .Prompt }}}}<|im_start|>user
{{{{ .Prompt }}}}
<|im_start|>assistant
{{{{ end }}}}{{{{ .Response }}}}
\"\"\"

SYSTEM \"\"\"You are the Humanizer Writing Agent. You only do two jobs:
1. REWRITE — change tone/style of selected text with bold edits to word choice, structure, and length.
2. GENERATE — expand short notes, bullets, or prompts into complete emails or essays.
For emails: produce a full send-ready message with subject, greeting, body, and sign-off as appropriate. Decide structure from context and user notes — not a rigid template.
Never do minimal grammar-only fixes. Return only the final plain text.\"\"\"

PARAMETER temperature 0.55
PARAMETER top_p 0.9
PARAMETER num_ctx 4096
PARAMETER stop "<|endoftext|>"
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fine-tune Qwen2.5-7B for grammar with MLX LoRA on Apple Silicon"
    )
    parser.add_argument(
        "--prepare-only",
        action="store_true",
        help="Convert train_data.jsonl to MLX chat JSONL (or legacy pairs), then exit",
    )
    parser.add_argument(
        "--legacy-data",
        action="store_true",
        help="Use grammar_rules.json + test_data pairs instead of train_data.jsonl",
    )
    parser.add_argument(
        "--export-only",
        action="store_true",
        help="Fuse existing LoRA adapter and export GGUF/Modelfile (skip training)",
    )
    parser.add_argument(
        "--skip-export",
        action="store_true",
        help="Train only; skip fuse/GGUF/Ollama export",
    )
    parser.add_argument("--iters", type=int, default=400, help="Training iterations")
    parser.add_argument(
        "--max-seq-length",
        type=int,
        default=384,
        help="Max tokens per training example (tone rewrites need more room than grammar)",
    )
    parser.add_argument(
        "--tone-target-fraction",
        type=float,
        default=0.35,
        help="Upsample rewrite_tone rows so this fraction of MLX train batches are tone (0=off)",
    )
    parser.add_argument("--lora-rank", type=int, default=8)
    parser.add_argument("--learning-rate", type=float, default=1e-5)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--num-layers", type=int, default=8)
    parser.add_argument("--grad-accumulation-steps", type=int, default=4)
    parser.add_argument(
        "--quantization",
        default="q4_k_m",
        help="GGUF quantization after f16 conversion (q4_k_m, q8_0, f16)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    use_prepared = TRAIN_DATA_PATH.is_file() and not args.legacy_data

    if args.export_only:
        export_for_ollama(quantization=args.quantization)
        log("export-only: done.")
        return

    if use_prepared:
        data_dir, num_examples = prepare_mlx_from_prepared_data(
            max_seq_length=args.max_seq_length,
            tone_target_fraction=args.tone_target_fraction,
        )
        if args.prepare_only:
            log("prepare-only: done.")
            return
        train_with_mlx(
            data_dir=data_dir,
            num_examples=num_examples,
            iters=args.iters,
            max_seq_length=args.max_seq_length,
            lora_rank=args.lora_rank,
            learning_rate=args.learning_rate,
            batch_size=args.batch_size,
            num_layers=args.num_layers,
            grad_accumulation_steps=args.grad_accumulation_steps,
        )
    else:
        if not args.legacy_data and not TRAIN_DATA_PATH.is_file():
            log(f"ERROR: Missing {TRAIN_DATA_PATH}")
            log("Run: .venv/bin/python prepare_data.py")
            log("Or pass --legacy-data to use the small grammar-only dataset.")
            raise SystemExit(1)

        pairs = merge_training_pairs()
        if not pairs:
            log("ERROR: No training pairs")
            raise SystemExit(1)

        if args.prepare_only:
            write_mlx_jsonl(pairs, max_seq_length=args.max_seq_length)
            log("prepare-only: done.")
            return

        train_with_mlx(
            pairs=pairs,
            num_examples=len(pairs),
            iters=args.iters,
            max_seq_length=args.max_seq_length,
            lora_rank=args.lora_rank,
            learning_rate=args.learning_rate,
            batch_size=args.batch_size,
            num_layers=args.num_layers,
            grad_accumulation_steps=args.grad_accumulation_steps,
        )

    if not args.skip_export:
        export_for_ollama(quantization=args.quantization)

    log("Done.")


if __name__ == "__main__":
    main()
