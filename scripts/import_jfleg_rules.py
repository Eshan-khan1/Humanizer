#!/usr/bin/env python3
"""Import JFLEG wrong/correct patterns into grammar_rules.json for RAG."""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
import urllib.request
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RULES_PATH = ROOT / "grammar_rules.json"
JFLEG_DIR = ROOT / "test_data" / "jfleg"

JFLEG_URLS = {
    "test.src": "https://raw.githubusercontent.com/keisks/jfleg/master/test/test.src",
    "test.ref0": "https://raw.githubusercontent.com/keisks/jfleg/master/test/test.ref0",
}

WORD_RE = re.compile(r"[A-Za-z0-9']+|\S")
PUNCT_ONLY = re.compile(r"^[\W_]+$")
AMBIGUOUS = {
    "to",
    "a",
    "an",
    "the",
    "on",
    "in",
    "is",
    "it",
    "i",
    "of",
    "at",
    "or",
    "and",
    "as",
    "be",
    "by",
    "for",
}
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


def likely_specific_pattern(wrong: str, correct: str) -> bool:
    if " " in wrong or " " in correct:
        return True
    if len(wrong) >= 4 and len(correct) >= 4:
        return True
    return False


def keep_pattern(wrong: str, correct: str, count: int, min_count: int) -> bool:
    if PUNCT_ONLY.match(wrong) or PUNCT_ONLY.match(correct):
        return False
    if len(wrong) <= 1 or len(correct) <= 1:
        return count >= max(min_count + 2, 5)
    if likely_specific_pattern(wrong, correct):
        return count >= min_count
    if wrong.lower() in AMBIGUOUS or correct.lower() in AMBIGUOUS:
        return count >= max(min_count + 2, 4)
    return count >= min_count + 1


def download_jfleg() -> None:
    JFLEG_DIR.mkdir(parents=True, exist_ok=True)
    for name, url in JFLEG_URLS.items():
        target = JFLEG_DIR / name
        if target.exists() and target.stat().st_size > 0:
            continue
        print(f"Downloading {url} …", file=sys.stderr)
        urllib.request.urlretrieve(url, target)


def load_sentence_pairs() -> list[tuple[str, str]]:
    source_lines = (JFLEG_DIR / "test.src").read_text(encoding="utf-8").splitlines()
    reference_lines = (JFLEG_DIR / "test.ref0").read_text(encoding="utf-8").splitlines()
    if len(source_lines) != len(reference_lines):
        raise ValueError(
            f"JFLEG line count mismatch: {len(source_lines)} src vs "
            f"{len(reference_lines)} ref"
        )
    return list(zip(source_lines, reference_lines))


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
    return slug[:80] or "pattern"


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
    base_id = f"jfleg-{slugify(wrong, correct)}"
    rule_id = base_id
    suffix = 2
    while rule_id in used_ids:
        rule_id = f"{base_id}-{suffix}"
        suffix += 1

    title = f"{wrong} → {correct}"
    keywords = keywords_for_phrase(wrong)
    if not keywords:
        keywords = [wrong.lower()]

    return {
        "id": rule_id,
        "category": "jfleg",
        "title": title,
        "keywords": keywords,
        "triggers": [wrong.lower()],
        "frequency": count,
        "rule": (
            f'Common JFLEG learner error (seen {count}x in test set): replace '
            f'"{wrong}" with "{correct}".'
        ),
        "examples": [{"wrong": wrong, "correct": correct}],
    }


def collect_patterns(
    pairs: list[tuple[str, str]], min_count: int
) -> list[tuple[str, str, int]]:
    counts: Counter[tuple[str, str]] = Counter()
    canonical: dict[tuple[str, str], tuple[str, str]] = {}

    for wrong, correct in pairs:
        key = (wrong.lower(), correct.lower())
        counts[key] += 1
        if key not in canonical:
            canonical[key] = (wrong, correct)

    ranked: list[tuple[str, str, int]] = []
    for key, count in counts.most_common():
        wrong, correct = canonical[key]
        if keep_pattern(wrong, correct, count, min_count):
            ranked.append((wrong, correct, count))
    return ranked


def import_jfleg_rules(min_count: int = 2, dry_run: bool = False) -> int:
    download_jfleg()
    sentence_pairs = load_sentence_pairs()

    extracted: list[tuple[str, str]] = []
    for source, reference in sentence_pairs:
        extracted.extend(extract_replace_pairs(source, reference))

    patterns = collect_patterns(extracted, min_count=min_count)
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
        f"JFLEG: {len(sentence_pairs)} sentence pairs, "
        f"{len(patterns)} common patterns, "
        f"{added} new rules added, "
        f"{skipped_duplicate} duplicates skipped.",
        file=sys.stderr,
    )
    return added


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--min-count",
        type=int,
        default=2,
        help="Minimum frequency to keep an error pattern (default: 2)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Analyze only; do not write grammar_rules.json",
    )
    args = parser.parse_args()
    added = import_jfleg_rules(min_count=args.min_count, dry_run=args.dry_run)
    if args.dry_run:
        print(f"Dry run complete ({added} rules would be added).")
    else:
        print(f"Updated {RULES_PATH} (+{added} jfleg rules).")


if __name__ == "__main__":
    main()
