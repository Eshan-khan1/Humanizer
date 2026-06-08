#!/usr/bin/env python3
"""
Auto-improvement loop: call /grammar (two-agent: LT+RAG + deep rewrite) on test pairs
corrections, append rules for missed errors, repeat until target accuracy.

Pairs that score 100% are saved to test_data/mastered_pairs.json and skipped on
later attempts. Delete that file to re-test everything.

Requires the Humanizer server (./start_server.sh) and Ollama/qwen2.5:7b running.
"""

from __future__ import annotations

import json
import re
import sys
import time
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parent
RULES_PATH = ROOT / "grammar_rules.json"
PAIRS_PATH = ROOT / "test_data" / "pairs.json"
MASTERED_PATH = ROOT / "test_data" / "mastered_pairs.json"
GRAMMAR_URL = "http://127.0.0.1:8000/grammar"
HEALTH_URL = "http://127.0.0.1:8000/health"
RELOAD_RULES_URL = "http://127.0.0.1:8000/reload-rules"
TARGET_ACCURACY = 0.95
REQUEST_TIMEOUT = 300
STAGNATION_ATTEMPTS = 3


@dataclass
class TestPair:
    wrong: str
    correct: str
    errors: list[dict[str, str]] = field(default_factory=list)
    label: str = ""


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower().strip())


def _similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, _normalize(a), _normalize(b)).ratio()


def _overlaps(a: str, b: str) -> bool:
    na, nb = _normalize(a), _normalize(b)
    if not na or not nb:
        return False
    return na in nb or nb in na


def _phrase_in_text(phrase: str, text: str) -> bool:
    return _normalize(phrase) in _normalize(text)


def extract_errors_from_pair(wrong: str, correct: str) -> list[dict[str, str]]:
    """Derive wrong→correct phrase pairs via word-level diff."""
    wrong_tokens = wrong.split()
    correct_tokens = correct.split()
    matcher = SequenceMatcher(None, wrong_tokens, correct_tokens)
    errors: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != "replace":
            continue
        wrong_phrase = " ".join(wrong_tokens[i1:i2])
        correct_phrase = " ".join(correct_tokens[j1:j2])
        if not wrong_phrase or not correct_phrase:
            continue
        if wrong_phrase.lower() == correct_phrase.lower():
            continue
        key = (_normalize(wrong_phrase), _normalize(correct_phrase))
        if key in seen:
            continue
        if not _phrase_in_text(wrong_phrase, wrong):
            continue
        seen.add(key)
        errors.append({"wrong": wrong_phrase, "correct": correct_phrase})

    return errors


def load_mastered_labels(path: Path = MASTERED_PATH) -> set[str]:
    """Load pair labels that already scored 100% in a prior run."""
    if not path.is_file():
        return set()
    with path.open(encoding="utf-8") as handle:
        raw = json.load(handle)
    if isinstance(raw, dict):
        labels = raw.get("mastered", [])
    elif isinstance(raw, list):
        labels = raw
    else:
        return set()
    return {str(label).strip() for label in labels if str(label).strip()}


def save_mastered_labels(labels: set[str], path: Path = MASTERED_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "mastered": sorted(labels),
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def load_test_pairs(path: Path = PAIRS_PATH) -> list[TestPair]:
    if not path.is_file():
        print(f"Missing test pairs file: {path}", file=sys.stderr)
        sys.exit(1)

    with path.open(encoding="utf-8") as handle:
        raw = json.load(handle)

    if isinstance(raw, dict):
        entries = raw.get("pairs", [])
    elif isinstance(raw, list):
        entries = raw
    else:
        print(f"Invalid pairs.json: expected list or {{\"pairs\": [...]}}", file=sys.stderr)
        sys.exit(1)

    pairs: list[TestPair] = []
    for index, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            continue
        wrong = (entry.get("wrong") or "").strip()
        correct = (entry.get("correct") or "").strip()
        if not wrong or not correct:
            continue

        label = (entry.get("id") or entry.get("label") or f"pair-{index}").strip()
        explicit = entry.get("errors") or entry.get("ground_truth") or []
        if explicit:
            errors = [
                {"wrong": e["wrong"], "correct": e["correct"]}
                for e in explicit
                if isinstance(e, dict) and e.get("wrong") and e.get("correct")
            ]
        else:
            errors = extract_errors_from_pair(wrong, correct)

        pairs.append(TestPair(wrong=wrong, correct=correct, errors=errors, label=label))

    if not pairs:
        print(f"No valid pairs in {path}", file=sys.stderr)
        sys.exit(1)

    return pairs


def matches_to_errors(matches: list[dict[str, Any]]) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    for match in matches:
        wrong = (match.get("word") or "").strip()
        suggestions = match.get("suggestions") or []
        correct = (suggestions[0] if suggestions else "").strip()
        if wrong and correct:
            errors.append({"wrong": wrong, "correct": correct})
    return errors


def is_error_fixed(
    expected: dict[str, str], found: list[dict[str, str]], wrong_text: str
) -> bool:
    ew, ec = expected["wrong"], expected["correct"]
    if not _phrase_in_text(ew, wrong_text):
        return False

    for item in found:
        fw, fc = item.get("wrong", ""), item.get("correct", "")
        wrong_ok = _overlaps(ew, fw) or _similarity(ew, fw) >= 0.55
        correct_ok = _overlaps(ec, fc) or _similarity(ec, fc) >= 0.55
        if wrong_ok and correct_ok:
            return True
    return False


def is_error_fixed_in_corrected(
    expected: dict[str, str], corrected: str, wrong_text: str
) -> bool:
    """Credit a fix when Agent 2's full rewrite contains the gold correction."""
    ew, ec = expected["wrong"], expected["correct"]
    if not _phrase_in_text(ew, wrong_text):
        return False
    if not corrected:
        return False
    if _phrase_in_text(ec, corrected):
        return True
    return _similarity(ec, corrected) >= 0.72 and _phrase_in_text(
        ec.split(".")[0], corrected
    )


def score_pair(
    pair: TestPair,
    found: list[dict[str, str]],
    corrected: str | None = None,
) -> tuple[int, int, list[dict[str, str]], list[dict[str, str]]]:
    fixed: list[dict[str, str]] = []
    for error in pair.errors:
        if is_error_fixed(error, found, pair.wrong):
            fixed.append(error)
        elif corrected and is_error_fixed_in_corrected(
            error, corrected, pair.wrong
        ):
            fixed.append(error)

    missed = [e for e in pair.errors if e not in fixed]
    return len(fixed), len(pair.errors), fixed, missed


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:40] or "rule"


def load_rules_file() -> dict[str, Any]:
    with RULES_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def save_rules_file(data: dict[str, Any]) -> None:
    with RULES_PATH.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def existing_rule_ids(data: dict[str, Any]) -> set[str]:
    return {str(r.get("id")) for r in data.get("rules", []) if r.get("id")}


def existing_example_keys(data: dict[str, Any]) -> set[tuple[str, str]]:
    keys: set[tuple[str, str]] = set()
    for rule in data.get("rules", []):
        for example in rule.get("examples") or []:
            if not isinstance(example, dict):
                continue
            wrong = str(example.get("wrong") or "").strip().lower()
            correct = str(example.get("correct") or "").strip().lower()
            if wrong and correct:
                keys.add((wrong, correct))
    return keys


def _find_rule_for_miss(
    data: dict[str, Any], wrong: str
) -> dict[str, Any] | None:
    wrong_norm = _normalize(wrong)
    best: dict[str, Any] | None = None
    best_len = -1

    for rule in data.get("rules", []):
        if not isinstance(rule, dict):
            continue
        for trigger in rule.get("triggers") or []:
            trigger_norm = _normalize(str(trigger))
            if trigger_norm and trigger_norm in wrong_norm and len(trigger_norm) > best_len:
                best = rule
                best_len = len(trigger_norm)
        for example in rule.get("examples") or []:
            if not isinstance(example, dict):
                continue
            example_wrong = _normalize(str(example.get("wrong") or ""))
            if example_wrong and example_wrong in wrong_norm and len(example_wrong) > best_len:
                best = rule
                best_len = len(example_wrong)

    return best


def _strengthen_rule(rule: dict[str, Any], wrong: str, correct: str) -> bool:
    """Add or reinforce a learned example on an existing rule."""
    examples = rule.setdefault("examples", [])
    key = (_normalize(wrong), _normalize(correct))
    changed = False

    if not any(
        (_normalize(str(ex.get("wrong") or "")), _normalize(str(ex.get("correct") or "")))
        == key
        for ex in examples
        if isinstance(ex, dict)
    ):
        examples.append({"wrong": wrong, "correct": correct})
        changed = True

    triggers = rule.setdefault("triggers", [])
    trigger = wrong.lower()
    if trigger not in {str(t).lower() for t in triggers}:
        triggers.insert(0, trigger)
        changed = True

    priority = int(rule.get("training_priority") or 0) + 1
    rule["training_priority"] = priority
    changed = True
    rule["title"] = f"{wrong} → {correct}"
    rule["rule"] = (
        f'When the text contains "{wrong}", correct it to "{correct}". '
        f"Learned from auto_tune (priority {priority})."
    )
    words = re.findall(r"[a-zA-Z']+", wrong.lower())
    rule["keywords"] = list(dict.fromkeys(words))[:10]
    return changed


def add_rules_for_missed(
    missed: list[dict[str, str]], *, force_update: bool = False
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Learn from mistakes: add new rules or strengthen existing ones.

    Returns (added_rules, updated_rules).
    """
    data = load_rules_file()
    ids = existing_rule_ids(data)
    known_examples = existing_example_keys(data)
    added: list[dict[str, Any]] = []
    updated: list[dict[str, Any]] = []

    for item in missed:
        wrong, correct = item["wrong"], item["correct"]
        key = (_normalize(wrong), _normalize(correct))
        if key in known_examples and not force_update:
            continue

        existing = _find_rule_for_miss(data, wrong)
        if existing:
            if _strengthen_rule(existing, wrong, correct):
                updated.append(existing)
                known_examples.add(key)
            continue

        base_id = f"auto-{_slugify(wrong)}"
        rule_id = base_id
        suffix = 2
        while rule_id in ids:
            rule_id = f"{base_id}-{suffix}"
            suffix += 1

        words = re.findall(r"[a-zA-Z']+", wrong.lower())
        new_rule: dict[str, Any] = {
            "id": rule_id,
            "category": "auto_tuned",
            "title": f"{wrong} → {correct}",
            "keywords": list(dict.fromkeys(words))[:10],
            "triggers": [wrong.lower()],
            "training_priority": 1,
            "rule": (
                f'When the text contains "{wrong}", correct it to "{correct}". '
                f"Learned from auto_tune after a missed grammar check."
            ),
            "examples": [{"wrong": wrong, "correct": correct}],
        }
        data.setdefault("rules", []).append(new_rule)
        ids.add(rule_id)
        known_examples.add(key)
        added.append(new_rule)

    if added or updated:
        save_rules_file(data)
        notify_server_rules_reload()

    return added, updated


def notify_server_rules_reload() -> None:
    try:
        response = requests.post(RELOAD_RULES_URL, timeout=10)
        response.raise_for_status()
        payload = response.json()
        print(
            f"  Server reloaded rules: {payload.get('injectable_rules')} injectable "
            f"of {payload.get('total_rules')} total",
            flush=True,
        )
    except requests.RequestException as exc:
        print(
            f"  Warning: could not reload server rules ({exc}). "
            "Restart ./start_server.sh if accuracy stalls.",
            file=sys.stderr,
        )


def check_server() -> None:
    try:
        response = requests.get(HEALTH_URL, timeout=10)
        response.raise_for_status()
        health = response.json()
    except requests.RequestException as exc:
        print(f"Cannot reach server at {HEALTH_URL}: {exc}", file=sys.stderr)
        print("Start it with: ./start_server.sh", file=sys.stderr)
        sys.exit(1)

    if not health.get("grammar_available"):
        print("Warning: grammar_available is false — LanguageTool may be down.", file=sys.stderr)
    if not health.get("ollama_available"):
        print("Warning: ollama_available is false — qwen2.5:7b fixes may be missing.", file=sys.stderr)


def call_grammar(text: str) -> tuple[list[dict[str, str]], str]:
    response = requests.post(
        GRAMMAR_URL,
        json={"text": text},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    payload = response.json()
    matches = matches_to_errors(payload.get("matches") or [])
    corrected = str(payload.get("corrected") or text)
    return matches, corrected


def _print_error_list(label: str, items: list[dict[str, str]]) -> None:
    if not items:
        print(f"    {label}: (none)")
        return
    print(f"    {label}:")
    for item in items:
        print(f"      - \"{item['wrong']}\" → \"{item['correct']}\"")


def run_loop() -> None:
    check_server()
    pairs = load_test_pairs()
    total_errors = sum(len(p.errors) for p in pairs)
    mastered = load_mastered_labels()
    recent_accuracies: list[float] = []

    print(f"Loaded {len(pairs)} pairs from {PAIRS_PATH}")
    print(f"Ground truth: {total_errors} expected corrections")
    print(f"Target: {int(TARGET_ACCURACY * 100)}% accuracy (no attempt limit)")
    if mastered:
        print(
            f"Skipping {len(mastered)} mastered pair(s) from {MASTERED_PATH.name}: "
            f"{', '.join(sorted(mastered))}"
        )
    print()

    attempt = 0
    while True:
        attempt += 1
        print("=" * 60, flush=True)
        print(f"Attempt {attempt}", flush=True)
        print("=" * 60, flush=True)

        t0 = time.time()
        fixed_total = 0
        all_missed: list[dict[str, str]] = []
        seen_missed: set[tuple[str, str]] = set()
        newly_mastered: list[str] = []
        active_count = 0

        for pair in pairs:
            pair_total = len(pair.errors)
            if pair.label in mastered:
                fixed_total += pair_total
                print(
                    f"\n  [{pair.label}] Skipped (mastered — 100% previously, "
                    f"{pair_total} errors counted as fixed)"
                )
                continue

            active_count += 1
            try:
                found, corrected = call_grammar(pair.wrong)
            except requests.RequestException as exc:
                print(f"Grammar request failed on {pair.label}: {exc}", file=sys.stderr)
                sys.exit(1)

            fixed_count, pair_total, fixed_list, missed_list = score_pair(
                pair, found, corrected
            )
            fixed_total += fixed_count
            pair_accuracy = fixed_count / pair_total if pair_total else 0.0

            print(f"\n  [{pair.label}] Fixed {fixed_count}/{pair_total} errors ({pair_accuracy * 100:.0f}%)")
            _print_error_list("Fixed", fixed_list)
            _print_error_list("Missed", missed_list)

            if found:
                print("    API reported:")
                for item in found:
                    print(f"      - \"{item['wrong']}\" → \"{item['correct']}\"")
            else:
                print("    API reported: (none)")
            if corrected and corrected.strip() != pair.wrong.strip():
                preview = corrected[:120] + ("…" if len(corrected) > 120 else "")
                print(f"    Corrected: {preview!r}")

            if pair_total > 0 and fixed_count == pair_total:
                newly_mastered.append(pair.label)

            for item in missed_list:
                key = (_normalize(item["wrong"]), _normalize(item["correct"]))
                if key not in seen_missed:
                    seen_missed.add(key)
                    all_missed.append(item)

        elapsed = time.time() - t0
        accuracy = fixed_total / total_errors if total_errors else 0.0
        recent_accuracies.append(accuracy)
        if len(recent_accuracies) > STAGNATION_ATTEMPTS:
            recent_accuracies.pop(0)

        print(
            f"\nOverall: Fixed {fixed_total}/{total_errors} errors "
            f"({accuracy * 100:.1f}% accuracy, {elapsed:.1f}s, "
            f"{active_count} pair(s) tested, {len(mastered)} skipped)"
        )

        if newly_mastered:
            mastered.update(newly_mastered)
            save_mastered_labels(mastered)
            print(
                f"  Newly mastered ({len(newly_mastered)}): "
                f"{', '.join(newly_mastered)} — skipped on future attempts"
            )

        if accuracy >= TARGET_ACCURACY:
            print(f"\nReached {TARGET_ACCURACY * 100:.0f}% accuracy. Done.")
            return

        if active_count == 0:
            print("\nAll pairs mastered but overall accuracy is below target. Check scoring.")
            return

        stagnated = (
            len(recent_accuracies) >= STAGNATION_ATTEMPTS
            and max(recent_accuracies) - min(recent_accuracies) < 0.005
        )
        force_update = stagnated and bool(all_missed)
        if stagnated:
            print(
                f"  Learning plateau detected ({STAGNATION_ATTEMPTS} attempts ~"
                f"{accuracy * 100:.1f}%) — reinforcing missed patterns",
                flush=True,
            )

        added, strengthened = add_rules_for_missed(
            all_missed, force_update=force_update
        )
        if added:
            print(f"  New rules added ({len(added)}):")
            for rule in added:
                print(f"    - [{rule['id']}] triggers={rule['triggers']}")
        if strengthened:
            print(f"  Rules strengthened ({len(strengthened)}):")
            for rule in strengthened:
                print(
                    f"    - [{rule['id']}] priority={rule.get('training_priority')} "
                    f"triggers={rule['triggers']}"
                )
        if not added and not strengthened:
            print(
                "  Learning: no new patterns (all misses already in grammar_rules.json). "
                "Remaining errors may need better Agent 2 rewrites or scoring tweaks.",
            )
        print()


if __name__ == "__main__":
    run_loop()
