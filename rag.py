"""Keyword- and phrase-based retrieval of grammar rules for RAG-augmented qwen2.5:7b prompts."""

from __future__ import annotations

import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

RULES_PATH = Path(__file__).resolve().parent / "grammar_rules.json"
DEFAULT_TOP_K = 5
MIN_RULE_FREQUENCY = 6  # dataset rules must appear more than 5 times

GENERIC_SINGLE_WORDS = frozenset({
    "to", "a", "an", "the", "on", "in", "is", "it", "i", "of", "at", "or", "and",
    "as", "be", "by", "for", "are", "was", "were", "you", "your", "have", "has",
    "do", "does", "we", "they", "he", "she", "this", "that", "these", "those",
    "if", "so", "not", "no", "us", "me", "my", "their", "there", "then", "than",
})

DATASET_RULE_CATEGORIES = frozenset({"grammar-correction", "jfleg"})

COMMON_SINGLE_WRONG_WORDS = frozenset({
    "me", "him", "her", "but", "and", "the", "a", "is", "was",
})

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
    _cached_unified_prompt_block.cache_clear()


def load_rules() -> list[dict[str, Any]]:
    """Load all grammar rules from grammar_rules.json."""
    data = _load_rules_data()
    rules = data.get("rules", [])
    if not isinstance(rules, list):
        return []
    return [rule for rule in rules if isinstance(rule, dict)]


def rule_frequency(rule: dict[str, Any]) -> int | None:
    """Return dataset frequency if known (explicit field or parsed from rule text)."""
    if "frequency" in rule:
        try:
            return int(rule["frequency"])
        except (TypeError, ValueError):
            return None
    match = re.search(r"seen (\d+)x", str(rule.get("rule") or ""), re.IGNORECASE)
    if match:
        return int(match.group(1))
    return None


def is_generic_single_word_rule(rule: dict[str, Any]) -> bool:
    """True for rules whose wrong side is a generic single word like in or the."""
    if str(rule.get("category") or "") == "auto_tuned":
        return False

    examples = rule.get("examples") or []
    if not examples or not isinstance(examples[0], dict):
        return False
    wrong = str(examples[0].get("wrong") or "").strip()
    correct = str(examples[0].get("correct") or "").strip()
    if " " in wrong:
        return False
    wrong_lower = wrong.lower()
    if wrong_lower in GENERIC_SINGLE_WORDS:
        return True
    if " " not in correct and correct.lower() in GENERIC_SINGLE_WORDS:
        return True
    return False


def _has_multiword_wrong_phrase(rule: dict[str, Any], min_words: int = 3) -> bool:
    for example in rule.get("examples") or []:
        if not isinstance(example, dict):
            continue
        wrong = str(example.get("wrong") or "").strip()
        if len(wrong.split()) >= min_words:
            return True
    return False


def is_injectable_rule(rule: dict[str, Any]) -> bool:
    """Filter low-confidence or overly generic rules before RAG injection."""
    if is_generic_single_word_rule(rule):
        return False

    examples = rule.get("examples") or []
    if examples and isinstance(examples[0], dict):
        wrong = str(examples[0].get("wrong") or "").strip()
        if wrong and " " not in wrong and wrong.lower() in COMMON_SINGLE_WRONG_WORDS:
            category = str(rule.get("category") or "")
            if not (
                category == "auto_tuned" and _has_multiword_wrong_phrase(rule, 3)
            ):
                return False

    category = str(rule.get("category") or "")
    freq = rule_frequency(rule)

    if category in DATASET_RULE_CATEGORIES:
        return freq is not None and freq >= MIN_RULE_FREQUENCY

    return True


def injectable_rules() -> list[dict[str, Any]]:
    """Rules eligible for qwen2.5:7b prompt injection."""
    return [rule for rule in load_rules() if is_injectable_rule(rule)]


def _rules_by_id() -> dict[str, dict[str, Any]]:
    return {
        str(rule.get("id")): rule
        for rule in injectable_rules()
        if rule.get("id")
    }


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

    if str(rule.get("category") or "") == "auto_tuned":
        score += 20.0
        score += float(rule.get("training_priority") or 0) * 3.0

    return score


def get_deep_fix_hints(text: str, top_k: int = 8) -> list[str]:
    """Build wrong→correct hints from auto_tuned rules present in the text."""
    text_lower = text.lower()
    rules = get_relevant_rules(text, top_k=top_k * 2)
    hints: list[str] = []
    seen: set[str] = set()

    for rule in rules:
        if str(rule.get("category") or "") != "auto_tuned":
            continue
        for example in rule.get("examples") or []:
            if not isinstance(example, dict):
                continue
            wrong = str(example.get("wrong") or "").strip()
            correct = str(example.get("correct") or "").strip()
            if not wrong or not correct:
                continue
            if wrong.lower() not in text_lower:
                continue
            hint = f'"{wrong}" → "{correct}"'
            if hint not in seen:
                seen.add(hint)
                hints.append(hint)
        if len(hints) >= top_k:
            break

    return hints[:top_k]


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
    """Format retrieved rules for injection into the qwen2.5:7b grammar prompt."""
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


def _ranges_overlap(
    a_offset: int, a_length: int, b_offset: int, b_length: int
) -> bool:
    return a_offset < b_offset + b_length and b_offset < a_offset + a_length


def _find_phrase_spans(text: str, phrase: str) -> list[tuple[int, int]]:
    """Return (offset, length) spans for phrase in text (case-insensitive)."""
    if not phrase:
        return []

    phrase_lower = phrase.lower()
    text_lower = text.lower()
    spans: list[tuple[int, int]] = []
    start = 0
    while True:
        idx = text_lower.find(phrase_lower, start)
        if idx == -1:
            break
        spans.append((idx, len(phrase)))
        start = idx + max(1, len(phrase))
    return spans


def _lt_covers_span(
    offset: int, length: int, lt_matches: list[dict[str, Any]]
) -> bool:
    """True when any LanguageTool match overlaps this text span."""
    for match in lt_matches:
        lt_offset = match.get("offset")
        lt_length = match.get("length")
        if not isinstance(lt_offset, int) or not isinstance(lt_length, int):
            continue
        if _ranges_overlap(offset, length, lt_offset, lt_length):
            return True
    return False


def _lt_matches_signature(lt_matches: list[dict[str, Any]]) -> str:
    parts = sorted(
        f"{match.get('offset')}:{match.get('length')}:{match.get('rule_id', '')}"
        for match in lt_matches
    )
    payload = "|".join(parts)
    return hashlib.sha256(payload.encode("utf-8", errors="ignore")).hexdigest()[:16]


def find_languagetool_gaps(
    text: str, lt_matches: list[dict[str, Any]]
) -> tuple[list[str], list[str]]:
    """
    Compare text + LanguageTool hits against grammar_rules.json.

    Returns (gap_hints, gap_rule_ids) for patterns present in the text that
    LanguageTool did not flag.
    """
    if not text or not text.strip():
        return [], []

    text_lower = text.lower()
    by_id = _rules_by_id()
    gap_hints: list[str] = []
    gap_rule_ids: list[str] = []
    seen_hints: set[str] = set()
    seen_rule_ids: set[str] = set()

    def add_gap(rule_id: str, wrong: str, correct: str) -> None:
        hint = f'"{wrong}" → "{correct}"'
        if hint in seen_hints:
            return
        seen_hints.add(hint)
        gap_hints.append(hint)
        if rule_id not in seen_rule_ids:
            seen_rule_ids.add(rule_id)
            gap_rule_ids.append(rule_id)

    for rule_id, rule in by_id.items():
        for example in rule.get("examples") or []:
            if not isinstance(example, dict):
                continue
            wrong = str(example.get("wrong") or "").strip()
            correct = str(example.get("correct") or "").strip()
            if not wrong or not correct:
                continue
            for offset, length in _find_phrase_spans(text, wrong):
                if not _lt_covers_span(offset, length, lt_matches):
                    add_gap(rule_id, wrong, correct)

        for trigger in rule.get("triggers") or []:
            phrase = str(trigger).strip()
            if not phrase or phrase.lower() not in text_lower:
                continue
            uncovered = any(
                not _lt_covers_span(offset, length, lt_matches)
                for offset, length in _find_phrase_spans(text, phrase)
            )
            if not uncovered:
                continue
            examples = rule.get("examples") or []
            if examples and isinstance(examples[0], dict):
                wrong = str(examples[0].get("wrong") or phrase).strip()
                correct = str(examples[0].get("correct") or "").strip()
                if correct:
                    add_gap(rule_id, wrong, correct)

    for pattern, rule_ids in PHRASE_PATTERN_RULES:
        match = re.search(pattern, text_lower)
        if not match:
            continue
        offset = match.start()
        length = match.end() - match.start()
        if _lt_covers_span(offset, length, lt_matches):
            continue
        for rule_id in rule_ids:
            rule = by_id.get(rule_id)
            if not rule:
                continue
            for example in rule.get("examples") or []:
                if not isinstance(example, dict):
                    continue
                wrong = str(example.get("wrong") or "").strip()
                correct = str(example.get("correct") or "").strip()
                if wrong and correct and wrong.lower() in text_lower:
                    add_gap(rule_id, wrong, correct)

    return gap_hints, gap_rule_ids


def get_rules_for_unified_pipeline(
    text: str,
    lt_matches: list[dict[str, Any]],
    top_k: int = DEFAULT_TOP_K,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Merge text-based RAG retrieval with rules for errors LanguageTool missed."""
    by_id = _rules_by_id()
    gap_hints, gap_rule_ids = find_languagetool_gaps(text, lt_matches)

    selected: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for rule_id in gap_rule_ids:
        if len(selected) >= top_k:
            break
        rule = by_id.get(rule_id)
        if rule and rule_id not in seen_ids:
            seen_ids.add(rule_id)
            selected.append(rule)

    for rule in get_relevant_rules(text, top_k=top_k):
        if len(selected) >= top_k:
            break
        rule_id = str(rule.get("id") or "")
        if rule_id and rule_id not in seen_ids:
            seen_ids.add(rule_id)
            selected.append(rule)

    return selected[:top_k], gap_hints


def _format_languagetool_summary(
    text: str, lt_matches: list[dict[str, Any]]
) -> list[str]:
    lines: list[str] = []
    for match in lt_matches[:25]:
        offset = match.get("offset", 0)
        length = match.get("length", 0)
        if isinstance(offset, int) and isinstance(length, int) and length > 0:
            wrong = text[offset : offset + length]
        else:
            wrong = str(match.get("word") or "").strip()
        suggestions = match.get("suggestions") or []
        fix = suggestions[0] if suggestions else "?"
        if wrong:
            lines.append(f'- "{wrong}" → "{fix}"')
    return lines


@lru_cache(maxsize=64)
def _cached_unified_prompt_block(
    rule_ids: tuple[str, ...],
    text_hash: str,
    lt_sig: str,
    text: str,
    gap_hints_key: str,
    lt_summary_key: str,
) -> str:
    by_id = _rules_by_id()
    rules = [by_id[rule_id] for rule_id in rule_ids if rule_id in by_id]
    gap_hints = [hint for hint in gap_hints_key.split("\n") if hint]
    lt_lines = [line for line in lt_summary_key.split("\n") if line]

    lines: list[str] = []
    if lt_lines:
        lines.append("LanguageTool already flagged these (do NOT re-report):")
        lines.extend(lt_lines)
        lines.append("")

    if gap_hints:
        lines.append("LanguageTool MISSED these — you MUST find and report them:")
        for hint in gap_hints:
            lines.append(f"- {hint}")
        lines.append("")

    rules_block = format_rules_for_prompt(rules, text=text)
    if rules_block:
        lines.append(rules_block)

    return "\n".join(lines).strip()


def prepare_grammar_rag_for_prompt(
    text: str,
    lt_matches: list[dict[str, Any]] | None = None,
    top_k: int = DEFAULT_TOP_K,
) -> tuple[str, dict[str, Any]]:
    """
    Select RAG rules and build the prompt block for qwen2.5:7b grammar checks.

    Returns (prompt_block, metadata) where metadata describes what was injected.
    """
    lt_matches = lt_matches or []
    total_rules = len(load_rules())
    eligible_rules = len(injectable_rules())

    if lt_matches:
        rules, gap_hints = get_rules_for_unified_pipeline(text, lt_matches, top_k=top_k)
        prompt_block = get_unified_grammar_prompt_block(text, lt_matches, top_k=top_k)
        mode = "unified"
    else:
        rules = get_relevant_rules(text, top_k=top_k)
        gap_hints = []
        prompt_block = get_relevant_rules_prompt_block(text, top_k=top_k)
        mode = "text_only"

    selected_rules = [
        {
            "id": str(rule.get("id") or ""),
            "title": str(rule.get("title") or rule.get("id") or "rule"),
            "category": str(rule.get("category") or ""),
        }
        for rule in rules
        if rule.get("id")
    ]

    metadata: dict[str, Any] = {
        "total_rules": total_rules,
        "eligible_rules": eligible_rules,
        "selected_count": len(selected_rules),
        "selected_rules": selected_rules,
        "gap_hint_count": len(gap_hints),
        "mode": mode,
        "prompt_block_chars": len(prompt_block),
        "injected": bool(prompt_block.strip()),
    }
    return prompt_block, metadata


def get_unified_grammar_prompt_block(
    text: str,
    lt_matches: list[dict[str, Any]],
    top_k: int = DEFAULT_TOP_K,
) -> str:
    """
    Unified RAG block: LanguageTool findings + gap analysis + relevant rules.

    Used after LanguageTool runs so qwen2.5:7b can catch what LT missed.
    """
    rules, gap_hints = get_rules_for_unified_pipeline(text, lt_matches, top_k=top_k)
    if not rules and not gap_hints and not lt_matches:
        return get_relevant_rules_prompt_block(text, top_k=top_k)

    rule_ids = tuple(
        sorted(str(rule.get("id", "")) for rule in rules if rule.get("id"))
    )
    text_hash = hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()
    lt_sig = _lt_matches_signature(lt_matches)
    gap_hints_key = "\n".join(gap_hints)
    lt_summary_key = "\n".join(_format_languagetool_summary(text, lt_matches))

    return _cached_unified_prompt_block(
        rule_ids,
        text_hash,
        lt_sig,
        text,
        gap_hints_key,
        lt_summary_key,
    )
