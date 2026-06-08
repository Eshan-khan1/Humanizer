#!/usr/bin/env python3
"""Import agentlans/grammar-correction patterns into grammar_rules.json for RAG."""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RULES_PATH = ROOT / "grammar_rules.json"
DATASET_NAME = "agentlans/grammar-correction"
DEFAULT_TOP_N = 500

WORD_RE = re.compile(r"[A-Za-z0-9']+|\S")
ALNUM_RE = re.compile(r"[A-Za-z0-9]")
PUNCT_ONLY = re.compile(r"^[\W_]+$")
SLUG_RE = re.compile(r"[^a-z0-9]+")


def tokenize(text: str) -> list[str]:
    return WORD_RE.findall(text)


def extract_replace_pairs(source: str, reference: str) -> list[tuple[str, str]]:
    """Extract wrong→correct replacement spans from a sentence pair."""
    source_tokens = tokenize(source)
    reference_tokens = tokenize(reference)
    pairs: list[tuple[str, str]] = []

    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(
        None, source_tokens, reference_tokens
    ).get_opcodes():
        if tag != "replace":
            continue
        wrong = " ".join(source_tokens[i1:i2]).strip()
        correct = " ".join(reference_tokens[j1:j2]).strip()
        if wrong and correct and wrong.lower() != correct.lower():
            pairs.append((wrong, correct))

    return pairs


def pattern_is_valid(wrong: str, correct: str) -> bool:
    if PUNCT_ONLY.match(wrong) or PUNCT_ONLY.match(correct):
        return False
    if not ALNUM_RE.search(wrong) or not ALNUM_RE.search(correct):
        return False
    return True


def load_sentence_pairs() -> list[tuple[str, str]]:
    try:
        from datasets import load_dataset
    except ImportError as exc:
        raise SystemExit(
            "Missing dependency: pip install datasets zstandard"
        ) from exc

    dataset = load_dataset(DATASET_NAME)
    pairs: list[tuple[str, str]] = []
    for split_name in ("train", "validation"):
        if split_name not in dataset:
            continue
        split = dataset[split_name]
        for row in split:
            source = str(row.get("input") or "").strip()
            reference = str(row.get("output") or "").strip()
            if source and reference:
                pairs.append((source, reference))
    return pairs


def collect_top_patterns(
    sentence_pairs: list[tuple[str, str]], top_n: int
) -> list[tuple[str, str, int]]:
    counts: Counter[tuple[str, str]] = Counter()
    canonical: dict[tuple[str, str], tuple[str, str]] = {}

    for source, reference in sentence_pairs:
        for wrong, correct in extract_replace_pairs(source, reference):
            key = (wrong.lower(), correct.lower())
            counts[key] += 1
            canonical.setdefault(key, (wrong, correct))

    ranked: list[tuple[str, str, int]] = []
    for key, count in counts.most_common():
        wrong, correct = canonical[key]
        if not pattern_is_valid(wrong, correct):
            continue
        ranked.append((wrong, correct, count))
        if len(ranked) >= top_n:
            break
    return ranked


def existing_example_keys(rules: list[dict]) -> set[tuple[str, str]]:
    keys: set[tuple[str, str]] = set()
    for rule in rules:
        for example in rule.get("examples") or []:
            if not isinstance(example, dict):
                continue
            wrong = str(example.get("wrong") or "").strip().lower()
            correct = str(example.get("correct") or "").strip().lower()
            if wrong and correct:
                keys.add((wrong, correct))
    return keys


def existing_rule_ids(rules: list[dict]) -> set[str]:
    return {str(rule.get("id")) for rule in rules if rule.get("id")}


def slugify(*parts: str) -> str:
    raw = "-".join(parts).lower()
    slug = SLUG_RE.sub("-", raw).strip("-")
    return slug[:72] or "pattern"


def keywords_for_phrase(phrase: str) -> list[str]:
    words = [token.lower() for token in WORD_RE.findall(phrase)]
    seen: set[str] = set()
    ordered: list[str] = []
    for word in words:
        if word and word not in seen:
            seen.add(word)
            ordered.append(word)
    return ordered[:8]


def build_rule(
    wrong: str,
    correct: str,
    count: int,
    used_ids: set[str],
) -> dict:
    base_id = f"gc-{slugify(wrong, correct)}"
    rule_id = base_id
    suffix = 2
    while rule_id in used_ids:
        rule_id = f"{base_id}-{suffix}"
        suffix += 1

    keywords = keywords_for_phrase(wrong) or [wrong.lower()]
    return {
        "id": rule_id,
        "category": "grammar-correction",
        "title": f"{wrong} → {correct}",
        "keywords": keywords,
        "triggers": [wrong.lower()],
        "frequency": count,
        "rule": (
            f'Common grammar-correction pattern (seen {count}x in '
            f"agentlans/grammar-correction): replace \"{wrong}\" with \"{correct}\"."
        ),
        "examples": [{"wrong": wrong, "correct": correct}],
    }


def import_grammar_correction_rules(
    top_n: int = DEFAULT_TOP_N,
    dry_run: bool = False,
) -> int:
    sentence_pairs = load_sentence_pairs()
    patterns = collect_top_patterns(sentence_pairs, top_n=top_n)

    data = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    rules: list[dict] = data.get("rules", [])
    known_examples = existing_example_keys(rules)
    used_ids = existing_rule_ids(rules)

    added = 0
    skipped_duplicate = 0
    for wrong, correct, count in patterns:
        key = (wrong.lower(), correct.lower())
        if key in known_examples:
            skipped_duplicate += 1
            continue
        rule = build_rule(wrong, correct, count, used_ids)
        rules.append(rule)
        used_ids.add(rule["id"])
        known_examples.add(key)
        added += 1

    data["rules"] = rules
    if not dry_run:
        RULES_PATH.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    print(
        f"grammar-correction: {len(sentence_pairs)} sentence pairs, "
        f"top {len(patterns)} frequent patterns, "
        f"{added} new rules added, "
        f"{skipped_duplicate} duplicates skipped.",
        file=sys.stderr,
    )
    return added


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--top-n",
        type=int,
        default=DEFAULT_TOP_N,
        help=f"Number of most frequent patterns to import (default: {DEFAULT_TOP_N})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Analyze only; do not write grammar_rules.json",
    )
    args = parser.parse_args()
    added = import_grammar_correction_rules(top_n=args.top_n, dry_run=args.dry_run)
    if args.dry_run:
        print(f"Dry run complete ({added} rules would be added).")
    else:
        print(f"Updated {RULES_PATH} (+{added} grammar-correction rules).")


if __name__ == "__main__":
    main()
