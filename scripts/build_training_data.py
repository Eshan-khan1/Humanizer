#!/usr/bin/env python3
"""
Build training pairs from JFLEG (HuggingFace), synthetic Ollama pairs, and merge into pairs.json.

Usage:
  python scripts/build_training_data.py
  python scripts/build_training_data.py --skip-synthetic   # JFLEG + merge only
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parent.parent
TEST_DATA = ROOT / "test_data"
PAIRS_PATH = TEST_DATA / "pairs.json"
JFLEG_PAIRS_PATH = TEST_DATA / "jfleg_pairs.json"
SYNTHETIC_PAIRS_PATH = TEST_DATA / "synthetic_pairs.json"

OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
OLLAMA_MODEL = "qwen2.5:7b"
OLLAMA_TIMEOUT_SEC = 300

SYNTHETIC_PROMPT = """Generate 30 wrong→correct sentence pairs for each of these error types.
Return ONLY valid JSON array, no explanation, no markdown.
Format: [{"wrong": "...", "correct": "..."}]
Error types:
1. there/their/they're confusion (10 pairs)
2. its/it's confusion (10 pairs)
3. your/you're confusion (10 pairs)
4. then/than confusion (10 pairs)
5. punctuation spacing errors like 'hello , world' (10 pairs)
6. missing apostrophes like 'dont, cant, wont' (10 pairs)"""


def log(message: str) -> None:
    print(message, flush=True)


def pair_dict(wrong: str, correct: str) -> dict[str, Any]:
    return {"wrong": wrong, "correct": correct, "errors": []}


def save_pairs(path: Path, pairs: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(pairs, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def load_pairs_file(path: Path) -> list[dict[str, Any]]:
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


def step1_download_jfleg() -> list[dict[str, Any]]:
    log("=" * 60)
    log("Step 1 — Download JFLEG from HuggingFace")
    log("=" * 60)

    try:
        from datasets import load_dataset
    except ImportError as exc:
        log("ERROR: datasets package not installed. Run: pip install datasets")
        raise SystemExit(1) from exc

    log("Loading jhu-clsp/jfleg (validation + test)…")
    dataset_names = ("jhu-clsp/jfleg", "jfleg")
    dataset = None
    last_error: Exception | None = None

    for name in dataset_names:
        try:
            validation = load_dataset(name, split="validation")
            test = load_dataset(name, split="test")
            dataset = list(validation) + list(test)
            log(f"Loaded dataset id: {name}")
            break
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            continue

    if dataset is None:
        log(f"ERROR: could not load JFLEG: {last_error}")
        raise SystemExit(1)

    pairs: list[dict[str, Any]] = []
    skipped_same = 0

    for row in dataset:
        wrong = str(row.get("sentence") or "").strip()
        corrections = row.get("corrections") or []
        if not wrong or not corrections:
            continue
        correct = str(corrections[0]).strip()
        if not correct or wrong == correct:
            skipped_same += 1
            continue
        pairs.append(pair_dict(wrong, correct))

    log(f"JFLEG rows processed: {len(dataset)}")
    log(f"Pairs with errors: {len(pairs)} (skipped {skipped_same} where wrong == correct)")
    save_pairs(JFLEG_PAIRS_PATH, pairs)
    log(f"Saved → {JFLEG_PAIRS_PATH}")
    return pairs


def _parse_json_array(raw: str) -> list[dict[str, Any]]:
    cleaned = (raw or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned).strip()

    try:
        data = json.loads(cleaned)
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if isinstance(data, dict):
            return [data]
    except json.JSONDecodeError:
        pass

    decoder = json.JSONDecoder()
    items: list[dict[str, Any]] = []
    offset = 0
    while offset < len(cleaned):
        chunk = cleaned[offset:].lstrip()
        if not chunk:
            break
        skip = len(cleaned[offset:]) - len(chunk)
        try:
            parsed, end = decoder.raw_decode(chunk)
        except json.JSONDecodeError:
            offset += skip + 1
            continue
        if isinstance(parsed, list):
            items.extend(item for item in parsed if isinstance(item, dict))
        elif isinstance(parsed, dict):
            items.append(parsed)
        offset += skip + end

    if items:
        return items

    object_re = re.compile(
        r'\{\s*"wrong"\s*:\s*"(?:[^"\\]|\\.)*"\s*,\s*"correct"\s*:\s*"(?:[^"\\]|\\.)*"\s*\}',
        re.DOTALL,
    )
    for match in object_re.finditer(cleaned):
        try:
            obj = json.loads(match.group())
            if isinstance(obj, dict):
                items.append(obj)
        except json.JSONDecodeError:
            continue

    if not items:
        raise ValueError("Ollama response contains no parseable wrong/correct pairs")
    return items


def step2_generate_synthetic() -> list[dict[str, Any]]:
    log("=" * 60)
    log("Step 2 — Generate synthetic homophone + punctuation pairs (Ollama)")
    log("=" * 60)

    log(f"POST {OLLAMA_URL} model={OLLAMA_MODEL} …")
    t0 = time.time()
    try:
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": OLLAMA_MODEL,
                "prompt": SYNTHETIC_PROMPT,
                "stream": False,
                "options": {"temperature": 0.4},
            },
            timeout=OLLAMA_TIMEOUT_SEC,
        )
        response.raise_for_status()
        body = response.json()
    except requests.RequestException as exc:
        log(f"ERROR: Ollama request failed: {exc}")
        log("Ensure Ollama is running: ollama serve && ollama pull qwen2.5:7b")
        raise SystemExit(1) from exc

    raw = (body.get("response") or "").strip()
    if not raw:
        log("ERROR: Ollama returned an empty response")
        raise SystemExit(1)

    log(f"Ollama responded in {time.time() - t0:.1f}s ({len(raw)} chars)")

    try:
        items = _parse_json_array(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        log(f"ERROR: could not parse synthetic JSON: {exc}")
        preview = raw[:500] + ("…" if len(raw) > 500 else "")
        log(f"Response preview: {preview}")
        raise SystemExit(1) from exc

    pairs: list[dict[str, Any]] = []
    skipped = 0
    for item in items:
        wrong = str(item.get("wrong") or "").strip()
        correct = str(item.get("correct") or "").strip()
        if not wrong or not correct or wrong == correct:
            skipped += 1
            continue
        pairs.append(pair_dict(wrong, correct))

    log(f"Parsed {len(items)} items from Ollama → {len(pairs)} valid pairs ({skipped} skipped)")
    save_pairs(SYNTHETIC_PAIRS_PATH, pairs)
    log(f"Saved → {SYNTHETIC_PAIRS_PATH}")
    return pairs


def _passes_filters(wrong: str, correct: str) -> bool:
    if wrong == correct:
        return False
    if len(wrong) <= 5 or len(wrong) >= 200:
        return False
    return True


def step3_merge(
    existing: list[dict[str, Any]],
    jfleg: list[dict[str, Any]],
    synthetic: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    log("=" * 60)
    log("Step 3 — Merge and deduplicate into pairs.json")
    log("=" * 60)

    sources = [
        ("existing pairs.json", existing),
        ("jfleg_pairs.json", jfleg),
        ("synthetic_pairs.json", synthetic),
    ]

    merged: list[dict[str, Any]] = []
    seen_wrong: set[str] = set()
    stats: dict[str, int] = {}

    for label, items in sources:
        added = 0
        filtered = 0
        duplicate = 0
        for item in items:
            wrong = str(item.get("wrong") or "").strip()
            correct = str(item.get("correct") or "").strip()
            if not wrong or not correct:
                filtered += 1
                continue
            if not _passes_filters(wrong, correct):
                filtered += 1
                continue
            key = wrong.lower()
            if key in seen_wrong:
                duplicate += 1
                continue
            seen_wrong.add(key)
            entry = pair_dict(wrong, correct)
            if item.get("errors"):
                entry["errors"] = item["errors"]
            merged.append(entry)
            added += 1
        stats[label] = added
        log(
            f"  {label}: +{added} added "
            f"({filtered} filtered, {duplicate} duplicates skipped)"
        )

    save_pairs(PAIRS_PATH, merged)
    log(f"Merged total: {len(merged)} pairs → {PAIRS_PATH}")
    if len(merged) < 500:
        log(f"NOTE: target is 500+ pairs; current total is {len(merged)}")
    else:
        log(f"Target met: {len(merged)} >= 500 pairs")
    return merged


def main() -> None:
    parser = argparse.ArgumentParser(description="Build test_data/pairs.json from JFLEG + synthetic data")
    parser.add_argument(
        "--skip-synthetic",
        action="store_true",
        help="Skip Ollama synthetic generation (use existing synthetic_pairs.json if present)",
    )
    args = parser.parse_args()

    log("build_training_data.py — starting")
    TEST_DATA.mkdir(parents=True, exist_ok=True)

    jfleg_pairs = step1_download_jfleg()

    if args.skip_synthetic:
        log("Skipping Step 2 (--skip-synthetic)")
        synthetic_pairs = load_pairs_file(SYNTHETIC_PAIRS_PATH)
        log(f"Loaded {len(synthetic_pairs)} pairs from {SYNTHETIC_PAIRS_PATH}")
    else:
        synthetic_pairs = step2_generate_synthetic()

    existing_pairs = load_pairs_file(PAIRS_PATH)
    step3_merge(existing_pairs, jfleg_pairs, synthetic_pairs)
    log("Done.")


if __name__ == "__main__":
    main()
