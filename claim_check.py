"""Detection-only claim checker for Generate drafts.

Extracts concrete details from a draft and classifies each against the seed
idea, factual permanent note, and profile. Also flags seed/note details that
are missing from the draft. Does not rewrite output — callers decide how to
surface findings (test harness checklist, logs, etc.).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

Classification = Literal["grounded", "restatement", "fabricated", "missing"]
SourceName = Literal["seed", "permanent_note", "profile"]

# Generic connective / email scaffolding — never treated as checkable claims.
_GENERIC = frozenset(
    {
        "hi", "hey", "hello", "dear", "there", "sir", "madam",
        "best", "sincerely", "regards", "thanks", "thank", "respectfully",
        "subject", "your", "name",
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
        "am", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "having", "do", "does", "did", "doing", "done",
        "will", "shall", "should", "can", "cannot", "could", "may", "might", "must",
        "would", "please", "let", "know", "need", "needs", "needed",
        "want", "wanted", "like", "ask", "asking", "tell", "told",
        "write", "writing", "written", "send", "sent", "share", "provide",
        "confirm", "confirmation", "discuss", "discussion", "consider", "considering",
        "appreciate", "appreciated", "hope", "looking", "forward", "reach", "out",
        "contact", "help", "assist", "assistance", "able", "unable", "happy", "glad",
        "possible", "possibility", "available", "availability",
        "regarding", "about", "concerning", "following", "follow", "up",
        "update", "updates", "status", "information", "details", "options",
        "response", "reply", "question", "questions", "request", "requesting",
        "requested", "message", "email", "note", "notes",
        "anything", "else", "further", "additional", "next", "steps", "step",
        "still", "already", "yet", "instead", "however", "currently",
        "make", "makes", "made", "making", "get", "got", "getting",
        "give", "given", "take", "took", "taken", "see", "saw", "seen",
        "come", "came", "go", "went", "say", "said", "keep", "kept",
        "include", "included", "including", "using", "used",
        "ensure", "complete", "completed", "proceed", "process",
        "convenience", "opportunity", "suggestion", "suggestions",
        "necessary", "important", "appropriate", "potential", "actual",
        "entire", "whole", "main", "primary", "final", "initial", "original",
        "previous", "prior", "future", "past", "present", "certain", "particular",
        "single", "multiple", "half", "full", "empty", "free", "high", "low",
        "long", "short", "small", "large", "big", "little", "good", "great",
        "fine", "sure", "okay", "ok", "well", "better", "soon", "ready",
        "here", "way", "ways", "thing", "things", "part", "parts",
        "kind", "kinds", "sort", "sorts", "type", "types", "level", "levels",
        "end", "side", "place", "area", "work", "works", "working",
        "kindly", "warmly", "quickly", "simply", "greatly",
        "hearing", "back", "once", "someone", "anyone", "everyone",
        "beginning", "accordingly", "significantly", "unfortunately",
        "appears", "particularly", "especially", "effectively",
        "everything", "slight", "current", "requires", "amount",
        "based", "reaching", "recently", "grant", "implementing", "inquire",
        "confirm", "proceed", "additional", "complete", "revised",
        "opportunity", "arrangement", "arrangements",
    }
)

_MONEY_RE = re.compile(r"\$[\d,]+(?:\.\d{2})?")
_ID_RE = re.compile(r"\b[A-Z]{1,5}-?\d{2,}\b|#\d{3,}\b")
_TIME_RE = re.compile(r"\b\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)\b", re.I)
_WEEKDAY_RE = re.compile(
    r"\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"mon|tue|wed|thu|fri|sat|sun)s?\b",
    re.I,
)
_MONTH_RE = re.compile(
    r"\b(?:january|february|march|april|may|june|july|august|september|"
    r"october|november|december)\b",
    re.I,
)
_RELATIVE_RE = re.compile(
    r"\b(?:next|this|last)\s+(?:week|weekend|month|year|"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
    re.I,
)
_DURATION_RE = re.compile(
    r"\b(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten)"
    r"(?:-\s*|\s+)(?:day|days|week|weeks|month|months)\b",
    re.I,
)
_PROPER_RE = re.compile(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3}\b")
_TOKEN_RE = re.compile(r"[A-Za-z0-9]+(?:'[A-Za-z]+)?|\$[\d,]+(?:\.\d{2})?")

# Soft paraphrase groups — any member can stand for any other in the group.
_RESTATE_GROUPS: tuple[frozenset[str], ...] = (
    frozenset({"rose", "risen", "rise", "increased", "increase", "higher", "up"}),
    frozenset({"costs", "cost", "prices", "price", "pricing"}),
    frozenset({"lost", "lose", "misplaced", "missing"}),
    frozenset({"ship", "ships", "shipping", "shipped", "dispatch", "dispatched", "replacements"}),
    frozenset({"three-day", "three days", "3 days", "3-day", "threeday"}),
    frozenset({"extension", "extend", "extended"}),
    frozenset({"deadline", "due"}),
    frozenset({"plumber", "plumbing"}),
    frozenset({"faucet", "tap", "drips", "dripping", "drip"}),
    frozenset({"lunch boxes", "lunch box", "lunchboxes", "lunchbox"}),
    frozenset({"fridays", "friday"}),
    frozenset({"remote", "remotely"}),
    frozenset({"piloted", "pilot", "covered", "already"}),
    frozenset({"quote", "quotation"}),
    frozenset({"revision", "revise", "revised"}),
    frozenset({"invoice", "invoices"}),
    frozenset({"samples", "sample", "packages", "package"}),
    frozenset({"courier", "courier service"}),
    frozenset({"steel", "steel costs"}),
    frozenset({"ethics essay", "ethics", "essay"}),
    frozenset({"bathroom", "bathroom faucet"}),
)

_STYLE_NOTE_RE = re.compile(r"(?i)^(?:style|tone)\s*:\s*")
_FACTUAL_LABEL_RE = re.compile(
    r"(?i)^(?:factual|fact|note|info(?:rmation)?)\s*:\s*"
)


@dataclass(frozen=True)
class ClaimFinding:
    detail: str
    classification: Classification
    source: SourceName | None = None
    expected_source: SourceName | None = None

    def format_line(self) -> str:
        if self.classification == "grounded":
            return f"  [grounded]     {self.detail}  ← {self.source}"
        if self.classification == "restatement":
            return f"  [restatement]  {self.detail}  ← {self.source}"
        if self.classification == "fabricated":
            return f"  [fabricated]   {self.detail}  (not in seed / permanent_note / profile)"
        # missing
        where = self.expected_source or "seed"
        return f"  [missing]      {self.detail}  (expected from {where})"


def _norm(text: str) -> str:
    text = (text or "").lower().replace("'", "")
    text = re.sub(r"[\u2013\u2014-]", " ", text)
    text = re.sub(r"[^a-z0-9$.\s#]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _stem(token: str) -> str:
    token = _norm(token).replace(" ", "")
    if token.endswith("ies") and len(token) > 4:
        return token[:-3] + "y"
    if token.endswith("ing") and len(token) > 5:
        return token[:-3]
    if token.endswith("ed") and len(token) > 4:
        return token[:-2]
    if token.endswith("es") and len(token) > 4:
        return token[:-2]
    if token.endswith("s") and len(token) > 3 and not token.endswith("ss"):
        return token[:-1]
    return token


def _variants(detail: str) -> set[str]:
    """Normalized literal forms of a detail (no paraphrase expansion)."""
    base = _norm(detail)
    out = {base, base.replace(" ", ""), _stem(base)}
    compact = base.replace(" ", "")
    out.add(compact)
    out.add(_stem(compact))
    return {v for v in out if v}


def _paraphrase_variants(detail: str) -> set[str]:
    """Literal forms plus soft paraphrase-group expansions."""
    out = set(_variants(detail))
    base = _norm(detail)
    compact = base.replace(" ", "")
    for group in _RESTATE_GROUPS:
        norms = {_norm(item) for item in group}
        compact_norms = {_norm(item).replace(" ", "") for item in group}
        if base in norms or compact in compact_norms:
            out |= norms
            out |= compact_norms
    return {v for v in out if v}


def _strip_email_scaffolding(draft: str) -> str:
    """Drop subject / greeting / sign-off so profile name signatures aren't claims."""
    lines: list[str] = []
    for line in (draft or "").splitlines():
        stripped = line.strip()
        if re.match(r"(?i)^subject\s*:", stripped):
            continue
        if re.match(r"(?i)^(hi|hey|hello|dear)\b", stripped) and len(stripped) < 60:
            continue
        if re.match(
            r"(?i)^(best|sincerely|thanks|thank you|regards|kind regards),?\s*$",
            stripped,
        ):
            break
        if stripped in {"[Your Name]"}:
            break
        lines.append(line)
    # Drop trailing signature-looking name line (1–3 Capitalized words).
    while lines:
        last = lines[-1].strip()
        if not last:
            lines.pop()
            continue
        if re.fullmatch(r"[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2}", last):
            lines.pop()
            continue
        break
    return "\n".join(lines)


def factual_permanent_note(permanent_note: str) -> str:
    """Keep factual content; drop style/tone directives and labels."""
    note = (permanent_note or "").strip()
    if not note:
        return ""
    if _STYLE_NOTE_RE.match(note):
        return ""
    return _FACTUAL_LABEL_RE.sub("", note).strip()


def _profile_text(profile: dict[str, Any] | None) -> str:
    if not profile:
        return ""
    bits: list[str] = []
    for key in (
        "fullName",
        "name",
        "jobTitle",
        "title",
        "companyName",
        "business",
        "company",
    ):
        value = profile.get(key)
        if isinstance(value, str) and value.strip():
            bits.append(value.strip())
    return " ".join(bits)


_COMPOUND_RE = re.compile(
    r"\b[A-Za-z][A-Za-z']+\s+"
    r"(?:boxes|box|costs|cost|tools|labs|essay|essays|faucet|faucets|"
    r"package|packages|samples|sample|invoice|invoices|quote|quotes|"
    r"extension|deadline|plumber|courier|shipment|shipments)\b",
    re.I,
)


def extract_claims(text: str, *, for_required: bool = False) -> list[str]:
    """Pull concrete, checkable details from text (order preserved, de-duped).

    When for_required=True (seed/note gap checks), skip weak ask-scaffolding
    tokens so verbs like "starting" are not treated as required claims.
    """
    raw = text or ""
    found: list[str] = []
    seen: set[str] = set()

    def _add(detail: str) -> None:
        detail = detail.strip()
        if not detail:
            return
        key = _norm(detail)
        if not key or key in _GENERIC or key in seen:
            return
        if key.isdigit() and len(key) <= 1:
            return
        seen.add(key)
        found.append(detail)

    for pattern in (
        _MONEY_RE,
        _ID_RE,
        _TIME_RE,
        _RELATIVE_RE,
        _DURATION_RE,
        _WEEKDAY_RE,
        _MONTH_RE,
        _COMPOUND_RE,
    ):
        for match in pattern.finditer(raw):
            _add(match.group(0))

    for match in _PROPER_RE.finditer(raw):
        phrase = match.group(0)
        first = _norm(phrase.split()[0])
        # Skip sentence-start determiners ("The cost") and lone generics.
        if first in _GENERIC or first in {"the", "a", "an", "this", "that", "these", "those"}:
            if len(phrase.split()) == 1:
                continue
            # Keep "Cobalt Tools"; drop "The Cost" / "The Quote".
            if first in {"the", "a", "an", "this", "that"}:
                continue
        _add(phrase)

    _weak_required = frozenset(
        {
            "starting", "started", "asking", "asked", "telling", "told",
            "email", "emailing", "writing", "request", "requesting",
            "reply", "replying", "needs", "need", "wanted", "want",
            "already", "piloted", "pilot", "director", "client", "buyer",
            "supervisor", "roommate", "professor", "team", "covered",
            "initial", "quotation", "discuss", "opportunity",
        }
    )

    tokens = [
        tok
        for tok in re.findall(r"[A-Za-z][A-Za-z']+", raw)
        if _norm(tok) not in _GENERIC and len(tok) >= 4
    ]
    for token in tokens:
        if for_required and _norm(token) in _weak_required:
            continue
        _add(token)

    return found


def _source_blob(text: str) -> str:
    return f" {_norm(text)} "


def _detail_in_source(detail: str, source_text: str) -> bool:
    if not source_text.strip():
        return False
    blob = _source_blob(source_text)
    for variant in _variants(detail):
        if len(variant) <= 2:
            continue
        if f" {variant} " in blob or variant in blob.replace(" ", ""):
            # Prefer word-ish containment for multi-char variants.
            if " " in variant or len(variant) >= 3:
                if variant in _norm(source_text) or variant.replace(" ", "") in _norm(
                    source_text
                ).replace(" ", ""):
                    return True
    # Token-level: every content token of the detail appears in source.
    parts = [p for p in _norm(detail).split() if p not in _GENERIC and len(p) >= 3]
    if parts and all(
        p in _norm(source_text) or _stem(p) in {_stem(t) for t in _norm(source_text).split()}
        for p in parts
    ):
        return True
    return False


def _is_restatement(detail: str, source_text: str) -> bool:
    if not source_text.strip():
        return False
    source_norm = _norm(source_text)
    source_tokens = set(source_norm.split())
    source_stems = {_stem(t) for t in source_tokens}

    for variant in _paraphrase_variants(detail):
        if variant in source_norm or variant.replace(" ", "") in source_norm.replace(
            " ", ""
        ):
            if variant not in _variants(detail):
                return True
            # Literal already handled by _detail_in_source; still True as soft match.
            if f" {variant} " in f" {source_norm} " or variant in source_tokens:
                continue

    detail_variants = _paraphrase_variants(detail)
    for group in _RESTATE_GROUPS:
        group_norms = {_norm(item) for item in group}
        if not (detail_variants & group_norms):
            continue
        if group_norms & source_tokens:
            return True
        if {_stem(g) for g in group_norms} & source_stems:
            return True

    detail_stems = {_stem(p) for p in _norm(detail).split() if p not in _GENERIC}
    if detail_stems and detail_stems <= source_stems:
        return True
    if detail_stems & source_stems and len(_norm(detail).split()) <= 2:
        return True
    return False


def _classify_against_sources(
    detail: str,
    *,
    seed: str,
    note: str,
    profile_text: str,
) -> ClaimFinding:
    # Priority: seed → permanent_note → profile.
    for name, text in (
        ("seed", seed),
        ("permanent_note", note),
        ("profile", profile_text),
    ):
        if _detail_in_source(detail, text):
            return ClaimFinding(detail, "grounded", source=name)  # type: ignore[arg-type]
    for name, text in (
        ("seed", seed),
        ("permanent_note", note),
        ("profile", profile_text),
    ):
        if _is_restatement(detail, text):
            return ClaimFinding(detail, "restatement", source=name)  # type: ignore[arg-type]

    # Multi-word detail: if every content token is grounded/restated in the
    # same source, treat the whole phrase as a restatement (e.g. "prices
    # increased" for "costs rose").
    parts = [
        part
        for part in re.findall(r"[A-Za-z0-9$]+", detail)
        if _norm(part) not in _GENERIC and len(part) >= 3
    ]
    if len(parts) >= 2:
        for name, text in (
            ("seed", seed),
            ("permanent_note", note),
            ("profile", profile_text),
        ):
            if all(
                _detail_in_source(part, text) or _is_restatement(part, text)
                for part in parts
            ):
                return ClaimFinding(detail, "restatement", source=name)  # type: ignore[arg-type]

    return ClaimFinding(detail, "fabricated")


def _required_source_details(seed: str, note: str) -> list[tuple[str, SourceName]]:
    """Concrete details that must appear in the draft (seed + factual note)."""
    required: list[tuple[str, SourceName]] = []
    seen: set[str] = set()
    for source_name, text in (("seed", seed), ("permanent_note", note)):
        if not text.strip():
            continue
        for detail in extract_claims(text, for_required=True):
            key = _norm(detail)
            if key in seen or key in _GENERIC:
                continue
            seen.add(key)
            required.append((detail, source_name))  # type: ignore[arg-type]
    return required


def claim_check_draft(
    draft: str,
    *,
    seed: str = "",
    permanent_note: str = "",
    profile: dict[str, Any] | None = None,
) -> list[ClaimFinding]:
    """Classify draft claims and flag missing seed/note specifics.

    Detection only — does not modify the draft.
    """
    body = _strip_email_scaffolding(draft)
    # Greeting/sign-off names still count for "was this detail dropped?"
    full_for_missing = draft or ""
    note = factual_permanent_note(permanent_note)
    profile_text = _profile_text(profile)
    findings: list[ClaimFinding] = []
    seen_detail: set[str] = set()

    for detail in extract_claims(body):
        key = _norm(detail)
        if key in seen_detail:
            continue
        seen_detail.add(key)
        findings.append(
            _classify_against_sources(
                detail, seed=seed, note=note, profile_text=profile_text
            )
        )

    for detail, source_name in _required_source_details(seed, note):
        key = _norm(detail)
        if any(
            f.classification in {"grounded", "restatement"}
            and (
                _norm(f.detail) == key
                or key in _paraphrase_variants(f.detail)
                or _norm(f.detail) in _paraphrase_variants(detail)
            )
            for f in findings
        ):
            continue
        if _detail_in_source(detail, full_for_missing) or _is_restatement(
            detail, full_for_missing
        ):
            continue
        findings.append(
            ClaimFinding(
                detail,
                "missing",
                expected_source=source_name,
            )
        )

    # Drop noisy fabricated bigrams when a unigram side was already flagged.
    fabricated_uni = {
        _norm(f.detail)
        for f in findings
        if f.classification == "fabricated" and " " not in f.detail
    }
    findings = [
        f
        for f in findings
        if not (
            f.classification == "fabricated"
            and " " in f.detail
            and any(part in fabricated_uni for part in _norm(f.detail).split())
        )
    ]

    # Drop missing bigrams when a unigram part is already marked missing,
    # or when a restatement/grounded finding already covers the phrase.
    missing_uni = {
        _norm(f.detail)
        for f in findings
        if f.classification == "missing" and " " not in f.detail
    }
    findings = [
        f
        for f in findings
        if not (
            f.classification == "missing"
            and " " in f.detail
            and any(part in missing_uni for part in _norm(f.detail).split())
        )
    ]

    return findings


def format_claim_checklist(findings: list[ClaimFinding]) -> list[str]:
    """Human-readable checklist lines for test harness output."""
    if not findings:
        return ["  (no concrete claims extracted)"]
    # Surface problems first, then grounded/restatement.
    order = {"fabricated": 0, "missing": 1, "restatement": 2, "grounded": 3}
    ordered = sorted(
        findings,
        key=lambda f: (order.get(f.classification, 9), _norm(f.detail)),
    )
    return [f.format_line() for f in ordered]


def claim_check_summary(findings: list[ClaimFinding]) -> str:
    counts = {"grounded": 0, "restatement": 0, "fabricated": 0, "missing": 0}
    for finding in findings:
        counts[finding.classification] = counts.get(finding.classification, 0) + 1
    return (
        f"{counts['fabricated']} fabricated, {counts['missing']} missing, "
        f"{counts['restatement']} restatement, {counts['grounded']} grounded"
    )
