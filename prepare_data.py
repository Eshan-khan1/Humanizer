#!/usr/bin/env python3
"""
Download HuggingFace datasets and build train_data.jsonl / val_data.jsonl.

Each line: {"task": str, "input": str, "output": str}

Usage:
  pip install -r requirements-finetune.txt
  .venv/bin/python prepare_data.py
  .venv/bin/python prepare_data.py --skip-c4   # faster dev run (coedit + jfleg only)
"""

from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, TextIO

ROOT = Path(__file__).resolve().parent
TEST_DATA = ROOT / "test_data"
TRAIN_PATH = ROOT / "train_data.jsonl"
VAL_PATH = ROOT / "val_data.jsonl"
TEMP_NAME = "prepare_data_combined.jsonl"
TONE_REWRITE_PATH = TEST_DATA / "Tone rewrite training data .json"
TONE_REWRITE_SOURCES = (
    TONE_REWRITE_PATH,
    TEST_DATA / "tone_rewrite_generated.jsonl",
    ROOT / "tone_rewrite_training_data_batch2.jsonl",
)

MAX_PAIRS = 500_000
TRAIN_FRACTION = 0.9
RANDOM_SEED = 3407

COEDIT_TASK_MAP = {
    "gec": "grammar",
    "formal": "rewrite_professional",
    "paraphrase": "rewrite_casual",
    "simplify": "rewrite_concise",
}

# Cap streaming for very large corpora so the temp file stays manageable.
C4_200M_STREAM_LIMIT = 400_000


def log(message: str) -> None:
    print(message, flush=True)


def write_pair(
    handle: TextIO,
    *,
    task: str,
    input_text: str,
    output_text: str,
) -> bool:
    input_text = input_text.strip()
    output_text = output_text.strip()
    if not input_text or not output_text:
        return False
    if input_text == output_text:
        return False
    record = {"task": task, "input": input_text, "output": output_text}
    handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return True


def strip_coedit_src(src: str) -> str:
    text = (src or "").strip()
    if ": " in text:
        return text.split(": ", 1)[1].strip()
    return text


def process_coedit(example: dict[str, Any]) -> dict[str, str] | None:
    raw_task = str(example.get("task") or "").strip().lower()
    mapped_task = COEDIT_TASK_MAP.get(raw_task)
    if not mapped_task:
        return None

    input_text = strip_coedit_src(str(example.get("src") or ""))
    output_text = str(example.get("tgt") or "").strip()
    if not input_text or not output_text or input_text == output_text:
        return None
    return {"task": mapped_task, "input": input_text, "output": output_text}


def process_jfleg(example: dict[str, Any]) -> dict[str, str] | None:
    input_text = str(example.get("sentence") or "").strip()
    corrections = example.get("corrections") or []
    if not input_text or not corrections:
        return None
    output_text = str(corrections[0]).strip()
    if not output_text or input_text == output_text:
        return None
    return {"task": "grammar", "input": input_text, "output": output_text}


def process_c4_200m(example: dict[str, Any]) -> dict[str, str] | None:
    input_text = str(example.get("input") or "").strip()
    output_text = str(example.get("output") or "").strip()
    if not input_text or not output_text or input_text == output_text:
        return None
    return {"task": "grammar", "input": input_text, "output": output_text}


def append_streaming_dataset(
    handle: TextIO,
    *,
    dataset_name: str,
    splits: list[str],
    process_fn: Callable[[dict[str, Any]], dict[str, str] | None],
    load_kwargs: dict[str, Any] | None = None,
    max_examples: int | None = None,
) -> int:
    from datasets import load_dataset

    load_kwargs = dict(load_kwargs or {})
    load_kwargs.setdefault("streaming", True)

    added = 0
    for split in splits:
        log(f"  streaming {dataset_name} [{split}] …")
        stream = load_dataset(dataset_name, split=split, **load_kwargs)
        for example in stream:
            if max_examples is not None and added >= max_examples:
                log(f"  reached limit ({max_examples:,}) for {dataset_name}")
                return added
            record = process_fn(example)
            if not record:
                continue
            if write_pair(
                handle,
                task=record["task"],
                input_text=record["input"],
                output_text=record["output"],
            ):
                added += 1
                if added % 50_000 == 0:
                    log(f"    … {added:,} pairs written from {dataset_name}")
    return added


def append_coedit(handle: TextIO) -> int:
    log("Processing grammarly/coedit …")
    return append_streaming_dataset(
        handle,
        dataset_name="grammarly/coedit",
        splits=["train", "validation"],
        process_fn=process_coedit,
    )


def append_jfleg(handle: TextIO) -> int:
    log("Processing jhu-clsp/jfleg …")
    return append_streaming_dataset(
        handle,
        dataset_name="jhu-clsp/jfleg",
        splits=["validation", "test"],
        process_fn=process_jfleg,
    )


def append_c4_200m(handle: TextIO) -> int:
    log("Processing liweili/c4_200m …")
    return append_streaming_dataset(
        handle,
        dataset_name="liweili/c4_200m",
        splits=["train"],
        process_fn=process_c4_200m,
        load_kwargs={"streaming": True, "revision": "refs/convert/parquet"},
        max_examples=C4_200M_STREAM_LIMIT,
    )


def parse_tone_rewrite_row(row: dict[str, Any]) -> dict[str, str] | None:
    prompt = str(row.get("prompt") or "").strip()
    completion = str(row.get("completion") or "").strip()
    if not prompt or not completion or "\n\n" not in prompt:
        return None

    instruction, input_text = prompt.rsplit("\n\n", 1)
    instruction = instruction.strip()
    input_text = input_text.strip()
    if not instruction or not input_text or input_text == completion:
        return None

    return {
        "task": "rewrite_tone",
        "instruction": instruction,
        "input": input_text,
        "output": completion,
    }


def append_tone_rewrite_pairs(
    handle: TextIO,
    paths: tuple[Path, ...] | None = None,
) -> int:
    """Append tone-rewrite prompt/completion pairs for LoRA training."""
    sources = paths or TONE_REWRITE_SOURCES
    seen: set[tuple[str, str]] = set()
    added = 0

    for path in sources:
        if not path.is_file():
            log(f"  tone rewrite: {path.name} not found — skipping")
            continue

        log(f"Appending tone rewrite pairs from {path.name} …")
        file_added = 0
        with path.open(encoding="utf-8") as source:
            for line_no, line in enumerate(source, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    log(f"  {path.name}:{line_no} skipped: {exc}")
                    continue
                record = parse_tone_rewrite_row(row)
                if not record:
                    continue
                key = (record["input"].lower(), record["output"].lower())
                if key in seen:
                    continue
                seen.add(key)
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                added += 1
                file_added += 1
        log(f"  +{file_added:,} from {path.name}")

    log(f"  total tone rewrite pairs: {added:,}")
    return added


def append_gyafc_pairs(handle: TextIO, folder: Path = ROOT) -> int:
    """
    Placeholder: append GYAFC pairs from gyafc_raw.jsonl if present.

    Expects each line: {"informal": "...", "formal": "..."}
    """
    gyafc_path = folder / "gyafc_raw.jsonl"
    if not gyafc_path.is_file():
        log(f"  gyafc_raw.jsonl not found at {gyafc_path} — skipping")
        return 0

    log(f"Appending GYAFC pairs from {gyafc_path} …")
    added = 0
    with gyafc_path.open(encoding="utf-8") as source:
        for line in source:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            informal = str(row.get("informal") or "").strip()
            formal = str(row.get("formal") or "").strip()
            if write_pair(
                handle,
                task="rewrite_professional",
                input_text=informal,
                output_text=formal,
            ):
                added += 1
    log(f"  added {added:,} GYAFC pairs")
    return added


def balance_for_tone_strength(
    lines: list[str],
    *,
    grammar_per_tone: float = 1.0,
    casual_per_tone: float = 0.5,
) -> list[str]:
    """Keep all tone rows; cap grammar/casual so tone is not drowned out."""
    tone_lines: list[str] = []
    by_task: dict[str, list[str]] = defaultdict(list)
    for line in lines:
        try:
            task = str(json.loads(line).get("task") or "unknown")
        except json.JSONDecodeError:
            task = "unknown"
        if task == "rewrite_tone":
            tone_lines.append(line)
        else:
            by_task[task].append(line)

    tone_count = len(tone_lines)
    if tone_count == 0:
        log("  tone-balance: no rewrite_tone rows — skipping balance step")
        return lines

    random.seed(RANDOM_SEED)
    balanced: list[str] = list(tone_lines)
    counts: dict[str, int] = {"rewrite_tone": tone_count}

    grammar_cap = max(1, int(round(tone_count * grammar_per_tone)))
    grammar_pool = by_task.get("grammar", [])
    if grammar_pool:
        picked = (
            grammar_pool
            if len(grammar_pool) <= grammar_cap
            else random.sample(grammar_pool, grammar_cap)
        )
        balanced.extend(picked)
        counts["grammar"] = len(picked)

    casual_cap = max(0, int(round(tone_count * casual_per_tone)))
    casual_pool = by_task.get("rewrite_casual", [])
    if casual_pool and casual_cap > 0:
        picked = (
            casual_pool
            if len(casual_pool) <= casual_cap
            else random.sample(casual_pool, casual_cap)
        )
        balanced.extend(picked)
        counts["rewrite_casual"] = len(picked)

    for task, pool in sorted(by_task.items()):
        if task in ("grammar", "rewrite_casual"):
            continue
        cap = max(1, tone_count // 20)
        picked = pool if len(pool) <= cap else random.sample(pool, cap)
        balanced.extend(picked)
        counts[task] = len(picked)

    random.shuffle(balanced)
    detail = ", ".join(f"{task}={count:,}" for task, count in sorted(counts.items()))
    log(
        f"Tone-balanced dataset: {len(balanced):,} pairs "
        f"({detail}; grammar_per_tone={grammar_per_tone}, casual_per_tone={casual_per_tone})"
    )
    return balanced


def cap_by_task_balance(lines: list[str], max_pairs: int) -> list[str]:
    if len(lines) <= max_pairs:
        return lines

    tone_lines: list[str] = []
    other_lines: list[str] = []
    for line in lines:
        try:
            task = json.loads(line).get("task", "unknown")
        except json.JSONDecodeError:
            task = "unknown"
        if task == "rewrite_tone":
            tone_lines.append(line)
        else:
            other_lines.append(line)

    tone_count = len(tone_lines)
    other_budget = max(0, max_pairs - tone_count)
    if len(other_lines) <= other_budget:
        sampled = tone_lines + other_lines
    else:
        by_task: dict[str, list[str]] = defaultdict(list)
        for line in other_lines:
            try:
                task = json.loads(line).get("task", "unknown")
            except json.JSONDecodeError:
                task = "unknown"
            by_task[str(task)].append(line)

        tasks = sorted(by_task)
        per_task = other_budget // len(tasks) if tasks else 0
        remainder = other_budget % len(tasks) if tasks else 0
        random.seed(RANDOM_SEED)

        sampled_others: list[str] = []
        for index, task in enumerate(tasks):
            quota = per_task + (1 if index < remainder else 0)
            pool = by_task[task]
            if len(pool) <= quota:
                sampled_others.extend(pool)
            else:
                sampled_others.extend(random.sample(pool, quota))
        sampled = tone_lines + sampled_others

    random.shuffle(sampled)
    log(
        f"Capped dataset from {len(lines):,} to {len(sampled):,} pairs "
        f"({tone_count:,} tone rewrite kept)"
    )
    return sampled


def shuffle_and_split(
    temp_path: Path,
    *,
    max_pairs: int = MAX_PAIRS,
    tone_balanced: bool = False,
    grammar_per_tone: float = 1.0,
    casual_per_tone: float = 0.5,
) -> tuple[int, int]:
    log("Reading combined temp file for shuffle/split …")
    with temp_path.open(encoding="utf-8") as handle:
        lines = [line for line in handle if line.strip()]

    if not lines:
        raise SystemExit("No training pairs were produced.")

    if tone_balanced:
        lines = balance_for_tone_strength(
            lines,
            grammar_per_tone=grammar_per_tone,
            casual_per_tone=casual_per_tone,
        )
    lines = cap_by_task_balance(lines, max_pairs)

    random.seed(RANDOM_SEED)
    random.shuffle(lines)

    split_at = int(len(lines) * TRAIN_FRACTION)
    train_lines = lines[:split_at]
    val_lines = lines[split_at:]

    with TRAIN_PATH.open("w", encoding="utf-8") as handle:
        handle.writelines(train_lines)
    with VAL_PATH.open("w", encoding="utf-8") as handle:
        handle.writelines(val_lines)

    return len(train_lines), len(val_lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build train_data.jsonl / val_data.jsonl")
    parser.add_argument(
        "--skip-c4",
        action="store_true",
        help="Skip liweili/c4_200m (faster; coedit + jfleg only)",
    )
    parser.add_argument(
        "--max-pairs",
        type=int,
        default=MAX_PAIRS,
        help=f"Cap total pairs after shuffle (default {MAX_PAIRS:,})",
    )
    parser.add_argument(
        "--tone-only",
        action="store_true",
        help="Build train/val JSONL from tone rewrite training data only (no HF download)",
    )
    parser.add_argument(
        "--tone-balanced",
        action="store_true",
        help="Cap grammar/casual to ~1:1 with tone rows so tone rewrite is not drowned out",
    )
    parser.add_argument(
        "--grammar-per-tone",
        type=float,
        default=1.0,
        help="When --tone-balanced: max grammar rows per tone row (default 1.0)",
    )
    parser.add_argument(
        "--casual-per-tone",
        type=float,
        default=0.5,
        help="When --tone-balanced: max casual rewrite rows per tone row (default 0.5)",
    )
    cli = parser.parse_args()

    if cli.tone_only:
        log("=" * 60)
        log("Preparing tone-rewrite training data only")
        log("=" * 60)
        temp_path = ROOT / TEMP_NAME
        with temp_path.open("w", encoding="utf-8") as handle:
            tone_count = append_tone_rewrite_pairs(handle)
        if tone_count == 0:
            raise SystemExit(
                "No tone rewrite pairs found. Generate some first:\n"
                "  .venv/bin/python scripts/generate_tone_data.py\n"
                f"Or add data to {TONE_REWRITE_PATH}"
            )
        train_count, val_count = shuffle_and_split(
            temp_path,
            max_pairs=tone_count,
            tone_balanced=cli.tone_balanced,
            grammar_per_tone=cli.grammar_per_tone,
            casual_per_tone=cli.casual_per_tone,
        )
        temp_path.unlink(missing_ok=True)
        log(f"Wrote {train_count:,} train + {val_count:,} val tone rewrite pairs")
        log(
            "Next: .venv/bin/python scripts/finetune_grammar_lora.py "
            "--prepare-only --tone-target-fraction 0.35"
        )
        return

    log("=" * 60)
    log("Preparing training data")
    log("=" * 60)

    temp_path = ROOT / TEMP_NAME
    totals: dict[str, int] = {}

    with temp_path.open("w", encoding="utf-8") as handle:
        totals["coedit"] = append_coedit(handle)
        totals["jfleg"] = append_jfleg(handle)
        if not cli.skip_c4:
            totals["c4_200m"] = append_c4_200m(handle)
        else:
            log("Skipping liweili/c4_200m (--skip-c4)")
            totals["c4_200m"] = 0
        totals["gyafc"] = append_gyafc_pairs(handle)
        totals["tone_rewrite"] = append_tone_rewrite_pairs(handle)

    log("")
    log("Dataset counts written to temp file:")
    for label, count in totals.items():
        log(f"  {label}: {count:,}")
    log(f"  total: {sum(totals.values()):,}")

    train_count, val_count = shuffle_and_split(
        temp_path,
        max_pairs=cli.max_pairs,
        tone_balanced=cli.tone_balanced,
        grammar_per_tone=cli.grammar_per_tone,
        casual_per_tone=cli.casual_per_tone,
    )
    temp_path.unlink(missing_ok=True)

    log("")
    log(f"Wrote {train_count:,} pairs → {TRAIN_PATH}")
    log(f"Wrote {val_count:,} pairs → {VAL_PATH}")
    log("Done.")


if __name__ == "__main__":
    main()
