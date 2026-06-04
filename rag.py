"""Keyword- and phrase-based retrieval of grammar rules for RAG-augmented Mistral prompts."""

from __future__ import annotations

import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

RULES_PATH = Path(__file__).resolve().parent / "grammar_rules.json"
DEFAULT_TOP_K = 8

_WORD_RE = re.compile(r"[a-zA-Z']+")

# High-confidence phrase patterns → rule ids (always included when matched)
PHRASE_PATTERN_RULES: list[tuple[str, list[str]]] = [
    (r"\bme and (him|her|them|us)\b", ["pronoun-order-subject", "sv-agreement-singular-plural"]),
    (r"\b(him|her|me|them|us) and (me|him|her|i)\b", ["pronoun-order-subject"]),
    (r"\bme and (him|her) was\b", ["pronoun-order-subject", "sv-agreement-singular-plural"]),
    (r"\bpacific\s+isle\b", ["confused-pacific-isle-specific-aisle", "confused-specific-pacific"]),
    (r"\bpacific\s+aisle\b", ["confused-pacific-isle-specific-aisle"]),
    (r"\bto\s+many\b", ["homophone-to-too-two", "confused-peoples"]),
    (r"\bpeoples\b", ["confused-peoples"]),
    (r"\bpeoples\s+packages\b", ["confused-peoples", "grammar-plural-package"]),
]


_rules_cache: dict[str, Any] | None = None
_rules_cache_mtime: float = 0.0


def _load_rules_data() -> dict[str, Any]:
    """Load grammar_rules.json, reloading when the file changes on disk."""
    global _rules_cache, _rules_cache_mtime
    mtime = RULES_PATH.stat().st_mtime
    if _rules_cache is None or mtime != _rules_cache_mtime:
        with RULES_PATH.open(encoding="utf-8") as handle:
            _rules_cache = json.load(handle)
        _rules_cache_mtime = mtime
    return _rules_cache


def reload_rules_cache() -> None:
    """Force the next load_rules() call to re-read grammar_rules.json."""
    global _rules_cache, _rules_cache_mtime
    _rules_cache = None
    _rules_cache_mtime = 0.0
    _cached_rules_prompt_block.cache_clear()


def load_rules() -> list[dict[str, Any]]:
    """Load all grammar rules from grammar_rules.json."""
    data = _load_rules_data()
    rules = data.get("rules", [])
    if not isinstance(rules, list):
        return []
    return [rule for rule in rules if isinstance(rule, dict)]


def _rules_by_id() -> dict[str, dict[str, Any]]:
    return {str(rule.get("id")): rule for rule in load_rules() if rule.get("id")}


def _tokenize(text: str) -> set[str]:
    return {token.lower() for token in _WORD_RE.findall(text)}


def _extract_ngrams(text_lower: str, max_n: int = 4) -> set[str]:
    words = _WORD_RE.findall(text_lower)
    ngrams: set[str] = set()
    for n in range(2, max_n + 1):
        for i in range(len(words) - n + 1):
            ngrams.add(" ".join(words[i : i + n]))
    return ngrams


def detect_phrase_hits(text_lower: str) -> list[tuple[str, list[str]]]:
    """Return (pattern, rule_ids) for each built-in phrase pattern that matches."""
    hits: list[tuple[str, list[str]]] = []
    for pattern, rule_ids in PHRASE_PATTERN_RULES:
        if re.search(pattern, text_lower):
            hits.append((pattern, rule_ids))
    return hits


def get_mandatory_rule_ids(text_lower: str) -> list[str]:
    """Rule ids that must be included based on phrase detection."""
    seen: set[str] = set()
    ordered: list[str] = []
    for _pattern, rule_ids in detect_phrase_hits(text_lower):
        for rule_id in rule_ids:
            if rule_id not in seen:
                seen.add(rule_id)
                ordered.append(rule_id)
    return ordered


def _rule_score(
    rule: dict[str, Any],
    text_tokens: set[str],
    text_lower: str,
    ngrams: set[str],
) -> float:
    score = 0.0

    for trigger in rule.get("triggers") or []:
        phrase = str(trigger).lower().strip()
        if phrase and phrase in text_lower:
            score += 12.0

    for keyword in rule.get("keywords") or []:
        key = str(keyword).lower().strip()
        if not key:
            continue
        if " " in key:
            if key in text_lower:
                score += 6.0
            elif key in ngrams:
                score += 5.0
            continue
        if key in text_tokens:
            score += 2.5
        elif key in text_lower:
            score += 1.0

    for ngram in ngrams:
        for keyword in rule.get("keywords") or []:
            key = str(keyword).lower().strip()
            if " " in key and key == ngram:
                score += 4.0

    for example in rule.get("examples") or []:
        if not isinstance(example, dict):
            continue
        wrong = str(example.get("wrong") or "").lower().strip()
        if not wrong:
            continue
        if wrong in text_lower:
            score += 15.0
        else:
            wrong_words = wrong.split()
            if len(wrong_words) >= 2 and all(w in text_tokens for w in wrong_words):
                score += 8.0

    return score


def get_relevant_rules(text: str, top_k: int = DEFAULT_TOP_K) -> list[dict[str, Any]]:
    """
    Return the top_k grammar rules most relevant to the user's text.

    Phrase-pattern hits are always included first, then highest-scoring rules.
    """
    if not text or not text.strip():
        return []

    by_id = _rules_by_id()
    if not by_id:
        return []

    text_lower = text.lower()
    text_tokens = _tokenize(text_lower)
    ngrams = _extract_ngrams(text_lower)

    selected: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for rule_id in get_mandatory_rule_ids(text_lower):
        rule = by_id.get(rule_id)
        if rule and rule_id not in seen_ids:
            seen_ids.add(rule_id)
            selected.append(rule)

    scored: list[tuple[float, str]] = []
    for rule_id, rule in by_id.items():
        if rule_id in seen_ids:
            continue
        score = _rule_score(rule, text_tokens, text_lower, ngrams)
        if score > 0:
            scored.append((score, rule_id))

    scored.sort(key=lambda item: item[0], reverse=True)

    for _score, rule_id in scored:
        if len(selected) >= top_k:
            break
        if rule_id not in seen_ids:
            seen_ids.add(rule_id)
            selected.append(by_id[rule_id])

    if selected:
        return selected[:top_k]

    fallback_ids = [
        "pronoun-order-subject",
        "homophone-to-too-two",
        "confused-pacific-isle-specific-aisle",
        "confused-peoples",
        "sv-agreement-singular-plural",
    ]
    return [by_id[rid] for rid in fallback_ids if rid in by_id][:top_k]


def _must_check_hints(text_lower: str, rules: list[dict[str, Any]]) -> list[str]:
    """Build explicit wrong→correct hints for the prompt from triggers and examples."""
    hints: list[str] = []
    seen: set[str] = set()

    for _pattern, rule_ids in detect_phrase_hits(text_lower):
        for rule_id in rule_ids:
            rule = _rules_by_id().get(rule_id)
            if not rule:
                continue
            for example in rule.get("examples") or []:
                if not isinstance(example, dict):
                    continue
                wrong = str(example.get("wrong") or "").strip()
                correct = str(example.get("correct") or "").strip()
                if not wrong or not correct:
                    continue
                if wrong.lower() in text_lower:
                    line = f'"{wrong}" → "{correct}"'
                    if line not in seen:
                        seen.add(line)
                        hints.append(line)

    for rule in rules:
        for trigger in rule.get("triggers") or []:
            phrase = str(trigger).lower().strip()
            if not phrase or phrase not in text_lower:
                continue
            for example in rule.get("examples") or []:
                if not isinstance(example, dict):
                    continue
                wrong = str(example.get("wrong") or "").lower()
                correct = str(example.get("correct") or "")
                if wrong and wrong in text_lower and correct:
                    line = f'"{wrong}" → "{correct}"'
                    if line not in seen:
                        seen.add(line)
                        hints.append(line)

    return hints


def format_rules_for_prompt(rules: list[dict[str, Any]], text: str = "") -> str:
    """Format retrieved rules for injection into the Mistral grammar prompt."""
    if not rules:
        return ""

    text_lower = (text or "").lower()
    hints = _must_check_hints(text_lower, rules)

    lines = [
        "Relevant grammar rules for this text:",
        "Apply EVERY rule below. Find ALL errors including spelling, homophones, confused words, punctuation, pronoun order, and subject-verb agreement.",
    ]

    if hints:
        lines.append("MUST CHECK these errors present in the text:")
        for hint in hints:
            lines.append(f"- {hint}")

    for index, rule in enumerate(rules, start=1):
        title = rule.get("title") or rule.get("id") or f"Rule {index}"
        body = rule.get("rule") or ""
        lines.append(f"- Rule {index} ({title}): {body}")
        for example in rule.get("examples") or []:
            if not isinstance(example, dict):
                continue
            wrong = example.get("wrong", "")
            correct = example.get("correct", "")
            if wrong and correct:
                lines.append(f"  Example: \"{wrong}\" → \"{correct}\"")

    lines.append("Use these rules to find errors. Report each wrong phrase exactly as it appears in the text.")
    return "\n".join(lines)


@lru_cache(maxsize=64)
def _cached_rules_prompt_block(
    rule_ids: tuple[str, ...], text_hash: str, text: str
) -> str:
    by_id = _rules_by_id()
    rules = [by_id[rule_id] for rule_id in rule_ids if rule_id in by_id]
    return format_rules_for_prompt(rules, text=text)


def get_relevant_rules_prompt_block(text: str, top_k: int = DEFAULT_TOP_K) -> str:
    """Retrieve rules and return formatted prompt block (cached per text + rules)."""
    rules = get_relevant_rules(text, top_k=top_k)
    rule_ids = tuple(
        sorted(str(rule.get("id", "")) for rule in rules if rule.get("id"))
    )
    text_hash = hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()
    return _cached_rules_prompt_block(rule_ids, text_hash, text)
