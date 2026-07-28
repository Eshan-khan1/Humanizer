#!/usr/bin/env python3
"""Run Test_data_generating_{N}.json matrices against the live Generate/Rewrite API."""

from __future__ import annotations

import argparse
import json
import re
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

from scripts.run_benchmarks import count_body_paragraphs

ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:8000"

TONE_MAP = {
    "formal": "formal",
    "friendly": "warm and friendly",
    "casual": "relaxed and casual",
    "blunt": "blunt and direct",
}
FAB = [
    "trim the hedge",
    "front door",
    "standup is moving",
    "friday standup",
    "cold nights",
    "considerable discomfort",
    "saturday in october",
    "factual:",
    "style:",
    "unforeseen circumstances",
    "personal circumstances",
    "health issues",
    "wedding cake",
    "this concerns a three",
    "this concerns a this",
]
SCAFFOLD = re.compile(
    r"(?i)\b(this concerns|the timing is|this relates to|this involves|the amount is)\b"
)

# Structural / greeting / sign-off / common Generate phrasing — never invent-warnings.
# Keep this to scaffolding only. Domain nouns (cake, vet, invoice…) must come from the idea.
_STRUCTURAL_ALLOW = frozenset(
    {
        # greetings / closings
        "hi", "hey", "hello", "dear", "there", "sir", "madam",
        "best", "sincerely", "regards", "thanks", "thank", "respectfully",
        # signature placeholder pieces
        "your", "name", "subject",
        # pronouns / function words
        "i", "me", "my", "mine", "we", "us", "our", "ours", "you", "your", "yours",
        "he", "him", "his", "she", "her", "hers", "they", "them", "their", "theirs",
        "it", "its", "this", "that", "these", "those", "who", "whom", "whose",
        "what", "which", "when", "where", "why", "how",
        "a", "an", "the", "and", "but", "or", "nor", "not", "no", "yes", "so", "too",
        "as", "at", "by", "for", "in", "of", "on", "to", "from", "with", "without",
        "into", "onto", "upon", "over", "under", "between", "among", "through",
        "during", "before", "after", "since", "until", "while", "because",
        "although", "though", "if", "unless", "whether", "than", "then",
        "also", "just", "very", "really", "quite", "rather", "almost", "enough",
        "some", "any", "all", "each", "every", "both", "either", "neither",
        "other", "others", "such", "same", "different", "more", "most", "less",
        "least", "few", "many", "much", "several", "various",
        # common verbs / auxiliaries (not domain content)
        "am", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "having", "do", "does", "did", "doing", "done",
        "will", "shall", "should", "can", "cannot", "could", "may", "might", "must",
        "would", "please", "let", "know", "need", "needs", "needed",
        "want", "wanted", "like", "ask", "asking", "tell", "told",
        "write", "writing", "written", "send", "sent", "share", "provide",
        "confirm", "confirmation", "discuss", "discussion", "consider", "considering",
        "appreciate", "appreciated", "hope", "looking", "forward", "reach", "out",
        "contact", "help", "assist", "assistance", "able", "unable", "happy", "glad",
        "possible", "possibility", "available", "availability", "flexible", "flexibility",
        "timing", "schedule", "regarding", "about", "concerning", "following", "follow",
        "up", "update", "updates", "status", "inquiry", "inquire", "enquire",
        "information", "details", "options", "response", "reply", "question", "questions",
        "issue", "issues", "concern", "concerns", "request", "requesting", "requested",
        "message", "email", "note", "notes", "draft",
        "anything", "else", "further", "additional", "next", "steps", "step",
        "still", "already", "yet", "instead", "also", "additionally", "however",
        "currently", "recent", "ongoing", "today", "tomorrow", "yesterday",
        "morning", "afternoon", "evening", "night", "time", "times",
        "day", "days", "week", "weeks", "month", "months", "year", "years",
        "one", "two", "three", "first", "second", "third", "last", "next",
        "new", "old", "good", "great", "fine", "sure", "okay", "ok", "well",
        "better", "best", "soon", "ready", "open", "closed", "true", "false",
        "make", "makes", "made", "making", "get", "got", "getting", "give", "given",
        "take", "took", "taken", "see", "saw", "seen", "come", "came", "go", "went",
        "say", "said", "keep", "kept", "leave", "left", "put", "set", "find", "found",
        "include", "included", "including", "using", "used", "based", "related",
        "ensure", "complete", "completed", "move", "forward", "proceed", "process",
        "convenience", "opportunity", "suggestions", "suggestion", "clarifying",
        "clarify", "restating", "restate", "generic", "specific", "general",
        "necessary", "important", "appropriate", "potential", "actual", "exact",
        "entire", "whole", "main", "primary", "final", "initial", "original",
        "previous", "prior", "future", "past", "present", "certain", "particular",
        "single", "multiple", "half", "full", "empty", "free", "high", "low",
        "long", "short", "small", "large", "big", "little",
        "test", "user", "reader", "recipient", "sender",
        "here", "way", "ways", "thing", "things", "part", "parts",
        "kind", "kinds", "sort", "sorts", "type", "types", "level", "levels",
        "per", "via", "etc", "unto",
        # polite filler that is not a fabricated domain fact
        "greatly", "kindly", "sincerely", "warmly", "quickly", "simply",
        "bring", "attention", "experiencing", "experience", "challenging",
        "another", "causing", "adjustments", "repairs", "work", "works", "working",
        "end", "side", "team", "office", "place", "area",
    }
)

_TOKEN_RE = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?|\$[\d,]+(?:\.\d{2})?|\b[A-Z]{1,5}-?\d{2,}\b|#\d{3,}\b|\d+(?:\.\d+)?")
_MONEY_RE = re.compile(r"\$[\d,]+(?:\.\d{2})?")
_ID_RE = re.compile(r"\b[A-Z]{1,5}-?\d{2,}\b|#\d{3,}\b")
_MEASURE_RE = re.compile(
    r"(?i)\b\d+(?:\.\d+)?\s*(?:inch|inches|in|cm|mm|ft|feet|lb|lbs|kg|oz|%)\b"
)
_WEEKDAY_RE = re.compile(
    r"(?i)\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b"
)
_MONTH_RE = re.compile(
    r"(?i)\b(?:january|february|march|april|may|june|july|august|september|"
    r"october|november|december)\b"
)


def _normalize_term(term: str) -> str:
    return re.sub(r"[^a-z0-9$#.-]", "", (term or "").lower())


def _profile_and_note_text(case: dict) -> str:
    settings = case.get("settings") or {}
    bits = [
        settings.get("profile") or "",
        settings.get("permanent_note") or "",
        case.get("idea") or case.get("original_text") or "",
    ]
    return " ".join(bits)


def extract_concrete_terms(text: str) -> set[str]:
    """Pull concrete / specific terms (content nouns-ish, money, IDs, measures)."""
    terms: set[str] = set()
    raw = text or ""
    for match in _MONEY_RE.finditer(raw):
        terms.add(_normalize_term(match.group(0)))
    for match in _ID_RE.finditer(raw):
        terms.add(_normalize_term(match.group(0)))
    for match in _MEASURE_RE.finditer(raw):
        terms.add(_normalize_term(match.group(0)))
        for piece in re.findall(r"[A-Za-z]+|\d+(?:\.\d+)?", match.group(0)):
            terms.add(_normalize_term(piece))
    for match in _WEEKDAY_RE.finditer(raw):
        terms.add(_normalize_term(match.group(0)))
    for match in _MONTH_RE.finditer(raw):
        terms.add(_normalize_term(match.group(0)))

    tokens = _TOKEN_RE.findall(raw)
    for token in tokens:
        norm = _normalize_term(token)
        if not norm or norm in _STRUCTURAL_ALLOW:
            continue
        if norm.isdigit() and len(norm) <= 2:
            continue
        # Content-ish tokens: longer words, proper-looking, money/id already added.
        if len(norm) >= 4 or norm[:1].isalpha() and any(ch.isdigit() for ch in norm):
            terms.add(norm)
        elif len(norm) >= 3 and norm not in _STRUCTURAL_ALLOW:
            # Short but specific (e.g. VPN, AC already allowlisted when common)
            if norm.isalpha() and norm == token.lower() and len(norm) >= 3:
                # Keep short content nouns that aren't structural (vet, cat, cake are allowlisted
                # as seed subjects when present in idea — still extract for seed set).
                terms.add(norm)

    # Simple adjective+noun / noun+noun bigrams for product-like specifics.
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z']+", raw.lower()) if w not in _STRUCTURAL_ALLOW]
    for left, right in zip(words, words[1:]):
        if len(left) >= 4 and len(right) >= 4:
            terms.add(f"{left} {right}")
    return {t for t in terms if t}


def invent_detail_warnings(case: dict, output: str) -> list[str]:
    """Flag output concrete terms not traceable to the idea / note / profile.

    Warnings only — expected false positives; for manual review.
    """
    if not (output or "").strip():
        return []
    seed_text = _profile_and_note_text(case)
    seed_terms = extract_concrete_terms(seed_text)
    seed_tokens = {
        _normalize_term(tok)
        for tok in _TOKEN_RE.findall(seed_text)
        if _normalize_term(tok)
    }
    profile = parse_profile((case.get("settings") or {}).get("profile") or "")
    for value in profile.values():
        if isinstance(value, str):
            for tok in _TOKEN_RE.findall(value):
                seed_tokens.add(_normalize_term(tok))

    # Ignore subject / greeting / signature scaffolding in the output scan.
    body_lines: list[str] = []
    for line in (output or "").splitlines():
        stripped = line.strip()
        if re.match(r"(?i)^subject\s*:", stripped):
            continue
        if re.match(r"(?i)^(hi|hey|hello|dear)\b", stripped) and len(stripped) < 48:
            continue
        if re.match(r"(?i)^(best|sincerely|thanks|thank you|regards),?\s*$", stripped):
            break
        if stripped in {"[Your Name]"}:
            break
        # Drop bare signature name line matching profile.
        full = (profile.get("fullName") or "").strip().lower()
        if full and stripped.lower() == full:
            break
        body_lines.append(line)
    body_text = "\n".join(body_lines)

    out_terms = extract_concrete_terms(body_text)
    # Prefer single-token flags first (less noisy than every adjective+noun bigram).
    unigrams = sorted(
        (t for t in out_terms if " " not in t),
        key=lambda t: (-len(t), t),
    )
    bigrams = sorted(
        (t for t in out_terms if " " in t),
        key=lambda t: (-len(t), t),
    )

    def _grounded(term: str) -> bool:
        if term in _STRUCTURAL_ALLOW:
            return True
        if term in seed_terms or term in seed_tokens:
            return True
        parts = term.split()
        if len(parts) > 1 and all(
            part in seed_terms or part in seed_tokens or part in _STRUCTURAL_ALLOW
            for part in parts
        ):
            return True
        if any(
            seed.startswith(term[:4]) or term.startswith(seed[:4])
            for seed in seed_tokens
            if len(seed) >= 4 and len(term) >= 4
        ):
            return True
        return False

    flagged: list[str] = []
    for term in unigrams + bigrams:
        if _grounded(term):
            continue
        # Skip bigrams once either side already flagged as a unigram invent.
        if " " in term:
            left, right = term.split(" ", 1)
            if left in flagged or right in flagged:
                continue
            # Skip bigrams that only add noise around an already-grounded seed noun.
            if left in seed_tokens or right in seed_tokens:
                continue
        flagged.append(term)
        if len(flagged) >= 10:
            break
    return flagged


def parse_profile(raw: str) -> dict:
    profile: dict = {"permanentNote": ""}
    for part in re.split(r",\s*", raw or ""):
        if ":" not in part:
            continue
        key, val = part.split(":", 1)
        key, val = key.strip().lower(), val.strip()
        if key in {"name", "full name"}:
            profile["fullName"] = val
        elif key in {"title", "job title"}:
            profile["jobTitle"] = val
        elif key in {"business", "company"}:
            profile["companyName"] = val
    return profile


def post(path: str, payload: dict) -> tuple[int, dict, float]:
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.time()
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            return (
                resp.status,
                json.loads(resp.read().decode()),
                round((time.time() - started) * 1000, 1),
            )
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read().decode())
        except Exception:
            body = {"detail": str(exc)}
        return exc.code, body, round((time.time() - started) * 1000, 1)
    except Exception as exc:
        return 0, {"detail": str(exc)}, round((time.time() - started) * 1000, 1)


def greeting_line(text: str) -> str:
    for line in (text or "").splitlines():
        stripped = line.strip()
        if re.match(r"^(Dear|Hi|Hey|Hello)\b", stripped, re.I):
            return stripped
    return ""


def flatten_cases(raw: dict | list, version: int) -> list[dict]:
    cases = raw["cases"] if isinstance(raw, dict) else raw
    flat: list[dict] = []
    for case in cases:
        # Rewrite cases may use original_text instead of idea.
        if case.get("feature") == "rewrite" and "original_text" in case:
            item = dict(case)
            item["idea"] = case["original_text"]
            item.setdefault("id", str(case.get("id") or case.get("test_id")))
            item.setdefault("scenario", case.get("scenario") or "")
            item.setdefault(
                "settings",
                {
                    "length": "short",
                    "tone": "formal",
                    "complexity": "standard",
                    "profile": "name: Test User",
                    "permanent_note": "",
                },
            )
            flat.append(item)
            continue
        if "idea" in case or ("checks" in case and "input" not in case):
            item = dict(case)
            item.setdefault("feature", "generate")
            item.setdefault("id", str(case.get("id") or case.get("test_id")))
            item.setdefault(
                "scenario", case.get("scenario") or case.get("test_name") or ""
            )
            item["idea"] = case.get("idea") or case.get("original_text") or ""
            flat.append(item)
            continue
        idea = case.get("input") or case.get("idea") or ""
        feature = case.get("feature") or "generate"
        variants = case.get("variants") or [{}]
        tid = case.get("test_id") or case.get("id") or len(flat) + 1
        name = case.get("test_name") or case.get("scenario") or f"test {tid}"
        for index, variant in enumerate(variants, 1):
            tone = variant.get("tone") or "friendly"
            length = variant.get("length") or "medium"
            complexity = variant.get("complexity") or "standard"
            profile = (
                variant.get("profile")
                or case.get("profile")
                or "name: Test User"
            )
            note = (
                variant.get("permanent_note")
                or case.get("permanent_note")
                or ""
            )
            flat.append(
                {
                    "id": f"{version}.{tid}.{index}",
                    "feature": (
                        feature
                        if feature in {"generate", "rewrite"}
                        else "generate"
                    ),
                    "scenario": f"{name} ({tone}/{length}/{complexity})",
                    "idea": idea,
                    "settings": {
                        "length": length,
                        "tone": tone,
                        "complexity": complexity,
                        "profile": profile,
                        "permanent_note": note,
                    },
                    "checks": case.get("checks") or {},
                }
            )
    return flat


def evaluate(
    case: dict, status: int, payload: dict, output: str
) -> tuple[list[str], list[str]]:
    checks = case.get("checks") or {}
    issues: list[str] = []
    warnings: list[str] = []
    if checks.get("reject_http_500") and status == 500:
        issues.append("unexpected HTTP 500")
    if status != 200:
        if not (checks.get("reject_http_500") and status == 500):
            issues.append(f"HTTP {status}: {payload.get('detail')}")
        return issues, warnings
    text = output or ""
    if not text.strip():
        issues.append("empty output")
        return issues, warnings
    lower = text.lower()
    seed = (case.get("idea") or "").lower()
    greet = greeting_line(text)
    if case.get("feature") == "generate":
        paras = count_body_paragraphs(text)
    else:
        paras = max(
            1,
            len([part for part in re.split(r"\n\s*\n", text) if part.strip()]),
        )
    for entity in checks.get("must_include_entities") or []:
        if entity.lower() not in lower:
            issues.append(f"missing entity: {entity}")
    for group in checks.get("must_include_any") or []:
        if not any(option.lower() in lower for option in group):
            issues.append(f"missing any of: {group}")
    for phrase in checks.get("forbid_phrases") or []:
        if phrase.lower() in lower:
            issues.append(f"forbidden phrase: {phrase}")
    for fact in checks.get("must_preserve_facts") or []:
        if fact.lower() not in lower:
            issues.append(f"missing preserved fact: {fact}")
    for actor in checks.get("must_preserve_actors") or []:
        if actor.lower() not in lower:
            issues.append(f"missing preserved actor: {actor}")
    if SCAFFOLD.search(text):
        issues.append(f"scaffold leak: {SCAFFOLD.search(text).group(0)!r}")
    want = checks.get("must_greeting_name")
    if want and not re.search(
        rf"^(Dear|Hi|Hey|Hello)\s+{re.escape(want)}\s*,?\s*$", greet, re.I
    ):
        issues.append(f"greeting missing name {want!r} (got {greet!r})")
    if checks.get("forbid_greeting_names"):
        if re.match(r"^(Dear|Hi|Hey|Hello)\s+[A-Z][a-z]+", greet) and not re.search(
            r"Sir or Madam|there\b", greet, re.I
        ):
            if not re.match(r"^(Hi|Hey),?\s*$", greet, re.I):
                issues.append(f"unexpected named greeting: {greet!r}")
    if (
        checks.get("must_include_entities")
        or checks.get("must_greeting_name")
        or checks.get("forbid_phrases")
    ):
        if checks.get("min_paragraphs") and paras < checks["min_paragraphs"]:
            issues.append(f"paragraphs {paras} < {checks['min_paragraphs']}")

    # General invent check (warnings only — for manual review).
    invent_flags = invent_detail_warnings(case, text)
    if invent_flags:
        warnings.append("possible invent: " + ", ".join(invent_flags))
    # Known catastrophic bleed phrases still surface as warnings if somehow missed.
    note = (case.get("settings") or {}).get("permanent_note", "").lower()
    for marker in FAB:
        if marker in lower and marker not in seed and marker not in note:
            msg = f"known bleed phrase: {marker}"
            if msg not in warnings and f"forbidden phrase: {marker}" not in issues:
                warnings.append(msg)
    return issues, warnings


def run_file(version: int, model: str) -> tuple[int, int, list[tuple[str, list[str]]]]:
    source = ROOT / f"Test_data_generating_{version}.json"
    destination = ROOT / f"Test_data_generating_{version}_results.text"
    raw = json.loads(source.read_text(encoding="utf-8"))
    cases = flatten_cases(raw, version)
    passed = failed = 0
    rows: list[dict] = []
    for index, case in enumerate(cases, 1):
        settings_raw = case.get("settings") or {}
        tone = settings_raw.get("tone") or "friendly"
        profile = parse_profile(settings_raw.get("profile") or "")
        if settings_raw.get("permanent_note"):
            profile["permanentNote"] = settings_raw["permanent_note"]
        settings = {
            "tonePreset": tone,
            "tone": TONE_MAP.get(tone, tone),
            "length": settings_raw.get("length") or "medium",
            "complexity": settings_raw.get("complexity") or "standard",
            "includeSubject": True,
            "profile": profile,
        }
        feature = case.get("feature") or "generate"
        idea = case.get("idea") or case.get("original_text") or ""
        if feature == "generate":
            status, body, ms = post(
                "/generate",
                {"text": idea, "format": "email", "settings": settings},
            )
            out = body.get("generated") if status == 200 else ""
        else:
            instruction = case.get("instruction") or TONE_MAP.get(tone, tone)
            status, body, ms = post(
                "/rewrite",
                {"text": idea, "tone": instruction},
            )
            out = body.get("rewritten") if status == 200 else ""
        issues, warnings = evaluate(case, status, body, out)
        ok = not issues
        passed += int(ok)
        failed += int(not ok)
        rows.append(
            {
                **case,
                "status": status,
                "ms": ms,
                "ok": ok,
                "issues": issues,
                "warnings": warnings,
                "output": out or body.get("detail") or "",
            }
        )
        warn_bit = f" WARN {warnings[0][:80]}" if warnings else ""
        print(
            f"v{version} [{index}/{len(cases)}] "
            f"{'PASS' if ok else 'FAIL'} {case.get('id')} ({ms}ms) "
            f"{issues[:2]}{warn_bit}",
            flush=True,
        )
    warn_count = sum(1 for row in rows if row.get("warnings"))
    lines = [
        f"Humanizer Generate/Rewrite Test Results — {source.name}",
        f"Writing model: {model}",
        f"Run: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"Summary: {passed}/{passed + failed} passed, {failed}/{passed + failed} failed",
        f"Invent warnings: {warn_count}/{passed + failed} cases flagged for review",
        "",
    ]
    for row in rows:
        lines += [
            f"[{'PASS' if row['ok'] else 'FAIL'}] {row.get('id')} — "
            f"{row.get('scenario')} ({row.get('feature')})",
            f"Settings: {json.dumps(row.get('settings') or {}, ensure_ascii=False)}",
            f"HTTP: {row['status']} | Duration: {row['ms']} ms",
            f"Issues: {'; '.join(row['issues']) if row['issues'] else 'None'}",
            f"Warnings: {'; '.join(row['warnings']) if row['warnings'] else 'None'}",
            "Output:",
            str(row["output"]),
            "",
            "-" * 80,
            "",
        ]
    destination.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {destination} — {passed}/{passed + failed}", flush=True)
    fails = [(str(row.get("id")), row["issues"]) for row in rows if not row["ok"]]
    return passed, failed, fails


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--versions",
        default="2-9",
        help="Comma list or range like 2-9 / 4,5,8",
    )
    args = parser.parse_args()
    versions: list[int] = []
    for part in args.versions.split(","):
        part = part.strip()
        if "-" in part:
            start, end = part.split("-", 1)
            versions.extend(range(int(start), int(end) + 1))
        elif part:
            versions.append(int(part))

    health = json.loads(
        urllib.request.urlopen(BASE + "/health", timeout=10).read().decode()
    )
    model = health.get("writing_model", "unknown")
    print(f"Writing model: {model}", flush=True)

    summary: list[tuple[int, int, int]] = []
    all_fails: list[tuple[int, str, list[str]]] = []
    for version in versions:
        path = ROOT / f"Test_data_generating_{version}.json"
        if not path.exists():
            continue
        print(f"\n===== {path.name} ({model}) =====", flush=True)
        passed, failed, fails = run_file(version, model)
        summary.append((version, passed, failed))
        all_fails.extend((version, case_id, issues) for case_id, issues in fails)

    print("\n======== OVERALL ========", flush=True)
    total_pass = total_fail = 0
    for version, passed, failed in summary:
        print(f"v{version}: {passed}/{passed + failed}", flush=True)
        total_pass += passed
        total_fail += failed
    print(f"TOTAL: {total_pass}/{total_pass + total_fail} on {model}", flush=True)
    if all_fails:
        print("\nFailures:", flush=True)
        for version, case_id, issues in all_fails:
            print(f"  v{version} {case_id}: {issues[:3]}", flush=True)

    summary_path = ROOT / f"Test_data_generating_{model.replace(':', '_').replace('/', '_')}_summary.text"
    summary_path.write_text(
        "\n".join(
            [
                "Qwen3 8B Generate/Rewrite full matrix summary",
                f"Model: {model}",
                f"Run: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                f"Total: {total_pass}/{total_pass + total_fail} passed",
                "",
                *[
                    f"v{version}: {passed}/{passed + failed}"
                    for version, passed, failed in summary
                ],
                "",
                "Failures:" if all_fails else "No failures.",
                *[
                    f"- v{version} {case_id}: {'; '.join(issues[:4])}"
                    for version, case_id, issues in all_fails
                ],
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(f"Wrote {summary_path}", flush=True)


if __name__ == "__main__":
    main()
