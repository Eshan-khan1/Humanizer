"""
Writing Agent — handles Rewrite and Generate only.

Separate from the grammar pipeline (Agent 1 LanguageTool + Agent 2 deep fixer).
Uses OLLAMA_WRITING_MODEL (default: humanizer-writing).
"""

from __future__ import annotations

import os
import re
from typing import Any, Literal

OLLAMA_WRITING_MODEL = os.environ.get("OLLAMA_WRITING_MODEL", "humanizer-writing")
OLLAMA_REWRITE_TEMPERATURE = float(os.environ.get("OLLAMA_REWRITE_TEMPERATURE", "0.55"))
OLLAMA_REWRITE_NUM_PREDICT = int(os.environ.get("OLLAMA_REWRITE_NUM_PREDICT", "1024"))
OLLAMA_GENERATE_TEMPERATURE = float(os.environ.get("OLLAMA_GENERATE_TEMPERATURE", "0.6"))
OLLAMA_GENERATE_NUM_PREDICT = int(os.environ.get("OLLAMA_GENERATE_NUM_PREDICT", "2048"))
OLLAMA_GENERATE_NUM_PREDICT_MEDIUM = int(
    os.environ.get("OLLAMA_GENERATE_NUM_PREDICT_MEDIUM", "2560")
)
OLLAMA_GENERATE_NUM_PREDICT_LONG = int(
    os.environ.get("OLLAMA_GENERATE_NUM_PREDICT_LONG", "3072")
)

WRITING_AGENT_SYSTEM_PROMPT = (
    "You are the Humanizer Writing Agent. You only do two jobs:\n"
    "1. REWRITE — change tone/style of selected text with bold edits to word choice, "
    "structure, and length.\n"
    "2. GENERATE — expand short notes, bullets, or prompts into complete emails or essays.\n"
    "For GENERATE: three independent settings — LENGTH (structure), TONE (sound), "
    "COMPLEXITY (vocabulary). Each controls one thing only; never let them bleed together. "
    "Apply all three simultaneously.\n"
    "Return only the final plain text — no markdown or meta explanations."
)

EMAIL_GENERATION_GUIDE = """\
TASK: GENERATE a complete email from the seed text, user notes, and document context.

Email structure:
  • Subject line (on its own first line: "Subject: ...") when enabled
  • Greeting — must follow the tone rules exactly
  • Body — must follow tone, length, and complexity rules exactly
  • Sign-off — must follow the tone rules; use the user's saved name from profile when available

General rules:
  • Produce send-ready text — no fragments, no "[mention ...]" placeholders, no meta instructions.
  • Weave informational user notes into the body naturally; do not paste them as a bullet list.
  • If a user note is informational only, it adds facts — it must not change tone or style.
  • If a user note includes a one-time tone instruction, follow that tone for this generation only.
  • Use exactly ONE blank line between major sections (after subject, between paragraphs).
  • If the seed is already a near-complete draft, polish and complete missing parts only."""

GENERATE_INDEPENDENCE_RULES = """\
INDEPENDENCE RULE (core constraint):
  Length, Tone, and Complexity are THREE SEPARATE instructions applied together.
  Never merge them into one instruction.
  Changing one setting while holding the other two fixed must ONLY change the
  dimension it controls.
  Example: Short + Formal + Advanced vs. Long + Formal + Advanced must differ
  ONLY in amount of text — not in formality or word choice."""

GENERATE_STRICT_RULES = """\
OUTPUT RULES (non-negotiable):
  • Hit the LENGTH structure exactly, regardless of tone or complexity.
  • Apply TONE to greeting, subject, body phrasing, and sign-off consistently.
  • Apply COMPLEXITY only to word choice within the required structure and tone.
  • Never invent recipient names (John, Jane, Sarah, Alice, Bob, etc.).
  • If a user profile is provided, apply it automatically (name, role, sign-off, etc.).
  • If profile/permanent note are empty: use generic phrasing with NO placeholder text
    (no [Name], no [Your Name], no bracketed blanks) and do not error.
  • Never leave bracketed instructions or template text in the output."""

GENERATE_LENGTH_GUIDANCE: dict[str, str] = {
    "short": """\
LENGTH — structure only (independent of tone and complexity):
  • Produce 1 short paragraph OR 2–3 sentences total for the body.
  • Just the core message — no padding, no warm-up, no filler.
  • Email: greeting and sign-off are allowed but the BODY is only the core message.
  • Essay: 1 short paragraph or 2–3 sentences total.
  • LENGTH must NEVER change vocabulary difficulty or tone — use the active tone and
    complexity settings unchanged; only produce less text.""",
    "medium": """\
LENGTH — structure only (independent of tone and complexity):
  • Produce 2–3 body paragraphs (separated by blank lines).
  • Email: include greeting, body (2–3 paragraphs), and closing/sign-off.
  • Essay: 2–3 paragraphs of content.
  • LENGTH must NEVER change vocabulary difficulty or tone — use the active tone and
    complexity settings unchanged; only produce a medium amount of text.""",
    "long": """\
LENGTH — structure only (independent of tone and complexity):
  • Produce 4 or more body paragraphs with full detail, context, and elaboration.
  • Email: greeting, 4+ body paragraphs, and closing/sign-off.
  • Essay: 4 or more paragraphs with supporting detail.
  • LENGTH must NEVER change vocabulary difficulty or tone — a "long, casual, simple"
    output must still use simple words and casual voice, just more of them.""",
}

GENERATE_COMPLEXITY_GUIDANCE: dict[str, str] = {
    "simple": """\
COMPLEXITY — vocabulary only (independent of length and tone):
  • Short, common words; short sentences; minimal jargon.
  • Prefer everyday words: get, ask, need, want, help, send, make, use, check, tell,
    push, moved, changed, because, so.
  • AVOID advanced/academic words: utilize, commence, facilitate, pursuant, regarding,
    inquire, subsequent, additionally, herein, comprehensive, expedite, endeavor.
  • COMPLEXITY must NEVER change tone or length — "simple" does not mean shorter output
    and does not change formality (TONE controls voice).""",
    "standard": """\
COMPLEXITY — vocabulary only (independent of length and tone):
  • Everyday professional vocabulary; moderate sentence length.
  • USE: provide, update, review, discuss, confirm, follow up, request, submit, appreciate.
  • AVOID: commence, pursuant, herein, thereof, overly academic jargon, and also avoid
    overly childish one-syllable-only phrasing.
  • COMPLEXITY must NEVER change tone or length — keep the active tone and paragraph count.""",
    "advanced": """\
COMPLEXITY — vocabulary only (independent of length and tone):
  • Sophisticated vocabulary and longer/more complex sentence structures.
  • USE precise terms where they fit: expedite, facilitate, comprehensive, subsequently,
    articulate, leverage, paramount, accordingly, endeavor, prior to.
  • Prefer varied sentence structure (clauses, transitions) over choppy simple sentences.
  • COMPLEXITY must NEVER change tone or length — "advanced" does not mean more formal
    and does not mean more paragraphs.""",
}

TONE_PRESET_GUIDANCE: dict[str, str] = {
    "formal": """\
TONE — voice/personality only (independent of length and complexity):
  • Professional language, no contractions, no slang, structured sentences.
  • Opening: "Dear …," when a recipient is known; otherwise "Dear Sir or Madam," or "Hello,"
  • Sign-off: "Sincerely," then the user's name from profile when saved; otherwise "Sincerely," alone
  • Subject line must sound formal
  • TONE must NEVER change how long the output is or how advanced the vocabulary is —
    "formal" does not mean longer, and does not mean more advanced words.""",
    "friendly": """\
TONE — voice/personality only (independent of length and complexity):
  • Warm, approachable, personable phrasing; contractions okay.
  • Opening: "Hi …," when a recipient is known; otherwise "Hi," or "Hi there,"
  • Sign-off: "Best," then the user's name from profile when saved; otherwise "Best," alone
  • Subject line must sound warm but clear
  • TONE must NEVER change how long the output is or how advanced the vocabulary is —
    "friendly" does not mean shorter or simpler words.""",
    "casual": """\
TONE — voice/personality only (independent of length and complexity):
  • Relaxed, conversational; contractions and informal phrasing okay.
  • Opening: "Hey …," when a recipient is known; otherwise "Hey," or "Hey there,"
  • Sign-off: "Thanks," then the user's name from profile when saved; otherwise "Thanks," alone
  • Subject line must sound informal
  • TONE must NEVER change how long the output is or how advanced the vocabulary is —
    "casual" does not mean shorter or simpler words.""",
}

TONE_EMAIL_CONVENTIONS: dict[str, str] = {
    "formal": (
        "Do NOT use casual openings (Hi, Hey) or casual sign-offs (Thanks, Best)."
    ),
    "friendly": (
        "Do NOT use formal openings (Dear) or formal sign-offs (Sincerely, Respectfully)."
    ),
    "casual": (
        'Do NOT use formal openings ("Dear") or formal sign-offs ("Sincerely") '
        'or stiff phrases ("I am writing to inform you").'
    ),
}

TONE_BANNED_FILLER_PHRASES = """\
BANNED FILLER (tone only — do not add or remove paragraphs to satisfy this):
  • Never invent padding just to sound polite.
  • Avoid stock lines: "Looking forward to hearing from you",
    "Thank you for your time and consideration", "Please do not hesitate to contact me"."""

_FORMAL_CONTRACTION_EXPANSIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bdon't\b", re.I), "do not"),
    (re.compile(r"\bdoesn't\b", re.I), "does not"),
    (re.compile(r"\bdidn't\b", re.I), "did not"),
    (re.compile(r"\bcan't\b", re.I), "cannot"),
    (re.compile(r"\bcouldn't\b", re.I), "could not"),
    (re.compile(r"\bwon't\b", re.I), "will not"),
    (re.compile(r"\bwouldn't\b", re.I), "would not"),
    (re.compile(r"\bshouldn't\b", re.I), "should not"),
    (re.compile(r"\bisn't\b", re.I), "is not"),
    (re.compile(r"\baren't\b", re.I), "are not"),
    (re.compile(r"\bwasn't\b", re.I), "was not"),
    (re.compile(r"\bweren't\b", re.I), "were not"),
    (re.compile(r"\bhaven't\b", re.I), "have not"),
    (re.compile(r"\bhasn't\b", re.I), "has not"),
    (re.compile(r"\bhadn't\b", re.I), "had not"),
    (re.compile(r"\bI'm\b"), "I am"),
    (re.compile(r"\bI've\b"), "I have"),
    (re.compile(r"\bI'll\b"), "I will"),
    (re.compile(r"\bI'd\b"), "I would"),
    (re.compile(r"\bwe're\b", re.I), "we are"),
    (re.compile(r"\bwe've\b", re.I), "we have"),
    (re.compile(r"\bwe'll\b", re.I), "we will"),
    (re.compile(r"\bthey're\b", re.I), "they are"),
    (re.compile(r"\bthey've\b", re.I), "they have"),
    (re.compile(r"\bit's\b", re.I), "it is"),
    (re.compile(r"\bthat's\b", re.I), "that is"),
    (re.compile(r"\bthere's\b", re.I), "there is"),
    (re.compile(r"\byou're\b", re.I), "you are"),
    (re.compile(r"\byou've\b", re.I), "you have"),
    (re.compile(r"\byou'll\b", re.I), "you will"),
    (re.compile(r"\blet's\b", re.I), "let us"),
)


def _apply_formal_tone_voice(text: str) -> str:
    """Expand contractions for formal tone only — does not change length or vocabulary level."""
    result = text
    for pattern, replacement in _FORMAL_CONTRACTION_EXPANSIONS:
        result = pattern.sub(replacement, result)
    return result

GENERATE_SHORT_CONTENT_RULES = """\
SHORT LENGTH CONTENT (mandatory when length is short):
  • 1 short paragraph or 2–3 sentences — core message only, no padding.
  • Include ONLY information from the seed input and any informational user note.
  • Never add sentences, instructions, or topics the user did not mention.
  • Do NOT add "please review changes", "provide feedback", "let me know if you have questions",
    or similar unless the user specifically said those in the input.
  • Do not change tone or vocabulary — LENGTH only controls how much text."""

TONE_PRESET_TO_VOICE: dict[str, str] = {
    "formal": "formal",
    "friendly": "warm and friendly",
    "casual": "relaxed and casual",
}

TONE_REWRITE_STRICT_RULES = """\
REWRITE RULES (non-negotiable):
  • Only change HOW the text sounds — same information, roughly the same length.
  • NEVER add sentences, lines, or phrases that were not in the original.
  • NEVER add: greeting lines, sign-off lines, closing thank-you lines, filler openers
    ("just a friendly reminder", "I wanted to reach out"), or exclamation marks unless
    the original already had them.
  • Only change words and sentence structure to match the requested tone.
  • If the user says "make it friendly", make the existing sentences sound warmer.
  • If the user says "make it formal", make the existing sentences sound more professional.
  • Nothing gets added; nothing removed except what is necessary to change the tone.
  • Output must read like the same message in a different voice — not a different message."""

TONE_REWRITE_OUTPUT_RULE = " Return only the rewritten text, nothing else."


def _clean_output(raw: str) -> str:
    cleaned = (raw or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:\w+)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in {'"', "'"}:
        cleaned = cleaned[1:-1].strip()
    cleaned = re.sub(
        r"^(?:here(?:'s| is) the (?:complete )?(?:rewritten |generated )?"
        r"(?:text|version|passage|email|essay)[:\s]*)\n?",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"^(?:(?:rewritten|generated) (?:text|version|passage)|output)[:\s]*\n?",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    return cleaned.strip()


def _normalize_email_spacing(text: str) -> str:
    if not text:
        return ""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    collapsed: list[str] = []
    previous_blank = False
    for line in normalized.split("\n"):
        is_blank = not line.strip()
        if is_blank:
            if not previous_blank:
                collapsed.append("")
            previous_blank = True
        else:
            collapsed.append(line)
            previous_blank = False
    return "\n".join(collapsed)


_REWRITE_FILLER_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bjust a friendly reminder\b", re.IGNORECASE),
    re.compile(r"\bjust a quick update\b", re.IGNORECASE),
    re.compile(r"\bi wanted to reach out\b", re.IGNORECASE),
    re.compile(r"\bi(?:'m| am) reaching out\b", re.IGNORECASE),
    re.compile(r"\b(?:i\s+)?hope you(?:'re|are)\s+doing\s+well\b", re.IGNORECASE),
    re.compile(r"\b(?:i\s+)?hope this(?:\s+email)?\s+finds\s+you\s+well\b", re.IGNORECASE),
    re.compile(r"\bjust wanted to\b", re.IGNORECASE),
    re.compile(r"\bjust checking in\b", re.IGNORECASE),
)

_REWRITE_THANKS_CLOSING_RE = re.compile(
    r"^(?:thanks|thank you)(?:\s+(?:so much|again|in advance|for your time|for considering(?:\s+my\s+request)?))?[,.]?\s*$",
    re.IGNORECASE,
)

_REWRITE_THANKS_SENTENCE_RE = re.compile(
    r"^(?:thanks|thank you)(?:\s+(?:so much|again|in advance|for your time|for considering(?:\s+my\s+request)?))?[.!]*\s*$",
    re.IGNORECASE,
)


def _rewrite_line_is_greeting(line: str) -> bool:
    return bool(_GREETING_LINE_RE.match(line.strip()))


def _rewrite_line_is_standalone_greeting(line: str) -> bool:
    stripped = line.strip()
    if not _rewrite_line_is_greeting(stripped):
        return False
    without_greeting = re.sub(
        r"^(?:Dear|Hi|Hey|Hello)\s+[^,\n]+,?\s*",
        "",
        stripped,
        flags=re.IGNORECASE,
    )
    return not without_greeting.strip()


def _rewrite_line_is_signoff(line: str) -> bool:
    return bool(_SIGNOFF_LINE_RE.match(line.strip()))


def _rewrite_line_is_thanks_closing(line: str) -> bool:
    return bool(
        _REWRITE_THANKS_CLOSING_RE.match(line.strip())
        or _REWRITE_THANKS_SENTENCE_RE.match(line.strip())
    )


def _rewrite_line_is_hope_filler(line: str) -> bool:
    stripped = line.strip()
    return bool(
        _HOPE_DOING_WELL_RE.search(stripped)
        or _HOPE_FINDS_WELL_RE.search(stripped)
    )


def _rewrite_content_line_count(text: str) -> int:
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    if len(lines) > 1:
        return sum(max(1, len(_split_sentences(line))) for line in lines)
    return len(_split_sentences(text))


def _remove_added_content_lines(original: str, rewritten: str) -> str:
    original_lines = [line.strip() for line in original.split("\n") if line.strip()]
    if len(original_lines) <= 1:
        return rewritten

    original_has_hope = any(_rewrite_line_is_hope_filler(line) for line in original_lines)
    kept_lines: list[str] = []
    for line in rewritten.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        stripped = line.strip()
        if not stripped:
            kept_lines.append(line)
            continue
        if _rewrite_line_is_hope_filler(stripped) and not original_has_hope:
            continue
        if _rewrite_sentence_is_filler(stripped) and _rewrite_sentence_overlap(stripped, original) < 0.45:
            continue
        kept_lines.append(line)
    return "\n".join(kept_lines).strip()


def _rewrite_sentence_words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9']+", text.lower()))


def _rewrite_sentence_overlap(sentence: str, original: str) -> float:
    sentence_words = _rewrite_sentence_words(sentence)
    if not sentence_words:
        return 1.0
    best = 0.0
    for original_sentence in _split_sentences(original):
        original_words = _rewrite_sentence_words(original_sentence)
        if not original_words:
            continue
        overlap = len(sentence_words & original_words) / max(len(sentence_words), len(original_words))
        best = max(best, overlap)
    return best


def _rewrite_sentence_is_filler(sentence: str) -> bool:
    return any(pattern.search(sentence) for pattern in _REWRITE_FILLER_PATTERNS)


def _rewrite_sentence_is_added(sentence: str, original: str, *, overlap_threshold: float = 0.2) -> bool:
    if _rewrite_sentence_is_filler(sentence):
        return _rewrite_sentence_overlap(sentence, original) < 0.45
    return _rewrite_sentence_overlap(sentence, original) < overlap_threshold


def _remove_added_greeting_signoff_lines(original: str, rewritten: str) -> str:
    original_has_greeting = any(_rewrite_line_is_greeting(line) for line in original.split("\n"))
    original_has_signoff = any(_rewrite_line_is_signoff(line) for line in original.split("\n"))
    original_has_thanks = any(_rewrite_line_is_thanks_closing(line) for line in original.split("\n"))

    lines = rewritten.replace("\r\n", "\n").replace("\r", "\n").split("\n")

    while lines:
        stripped = lines[0].strip()
        if not stripped:
            lines.pop(0)
            continue
        if not original_has_greeting and _rewrite_line_is_standalone_greeting(stripped):
            lines.pop(0)
            continue
        if not original_has_greeting and _rewrite_line_is_greeting(stripped):
            stripped = re.sub(
                r"^(?:Dear|Hi|Hey|Hello)\s+[^,\n]+,\s*",
                "",
                stripped,
                flags=re.IGNORECASE,
            )
            if stripped:
                lines[0] = stripped
            else:
                lines.pop(0)
            continue
        break

    while lines:
        stripped = lines[-1].strip()
        if not stripped:
            lines.pop()
            continue
        if not original_has_signoff and _rewrite_line_is_signoff(stripped):
            lines.pop()
            continue
        if not original_has_thanks and _rewrite_line_is_thanks_closing(stripped):
            lines.pop()
            continue
        if (
            not original_has_signoff
            and len(lines) >= 2
            and _rewrite_line_is_signoff(lines[-2].strip())
            and len(stripped.split()) <= 3
        ):
            lines.pop()
            continue
        break

    return "\n".join(lines).strip()


def _strip_rewrite_filler_phrases(text: str) -> str:
    result = text
    for pattern in _REWRITE_FILLER_PATTERNS:
        result = pattern.sub("", result)
    result = re.sub(r"^[—–\-:,.\s]+", "", result, flags=re.MULTILINE)
    result = re.sub(r"\s{2,}", " ", result)
    return result.strip()


def _strip_added_thanks_closing(original: str, rewritten: str) -> str:
    original_has_thanks = any(
        _rewrite_line_is_thanks_closing(line) or "thank you" in line.lower()
        for line in original.split("\n")
        if line.strip()
    )
    if original_has_thanks:
        return rewritten

    result = rewritten
    paragraphs = result.split("\n\n")
    cleaned_paragraphs: list[str] = []
    for paragraph in paragraphs:
        sentences = _split_sentences(paragraph)
        if not sentences:
            continue
        last = sentences[-1]
        if _rewrite_line_is_thanks_closing(last) or _REWRITE_THANKS_SENTENCE_RE.match(last.strip()):
            trimmed = re.sub(
                r"[,.\s]*(?:thanks|thank you)(?:\s+(?:so much|again|in advance|for your time|for considering(?:\s+my\s+request)?))?[.!]*\s*$",
                "",
                last,
                flags=re.IGNORECASE,
            ).strip()
            if trimmed:
                sentences[-1] = trimmed
            else:
                sentences.pop()
        if sentences:
            cleaned_paragraphs.append(_join_sentences(sentences))
    return "\n\n".join(cleaned_paragraphs).strip()


def _clean_rewrite_sentence(sentence: str) -> str:
    cleaned = _strip_rewrite_filler_phrases(sentence)
    cleaned = cleaned.strip(" ,;—–-")
    return cleaned.strip()


def _remove_added_filler_sentences(original: str, rewritten: str) -> str:
    paragraphs = rewritten.split("\n\n")
    filtered_paragraphs: list[str] = []
    for paragraph in paragraphs:
        sentences = _split_sentences(paragraph)
        kept: list[str] = []
        for sentence in sentences:
            cleaned = _clean_rewrite_sentence(sentence)
            if not cleaned:
                continue
            if _rewrite_sentence_is_filler(sentence):
                if _rewrite_sentence_overlap(cleaned, original) >= 0.25:
                    kept.append(cleaned)
                continue
            kept.append(cleaned)
        if kept:
            filtered_paragraphs.append(_join_sentences(kept))
    return "\n\n".join(filtered_paragraphs).strip()


def _strip_excess_rewrite_sentences(original: str, rewritten: str) -> str:
    original_count = _rewrite_content_line_count(original)
    if original_count == 0:
        return rewritten

    max_allowed = original_count + 1
    if len(_split_sentences(rewritten)) <= max_allowed:
        return rewritten
    paragraphs = rewritten.split("\n\n")
    all_sentences: list[str] = []
    paragraph_ranges: list[tuple[int, int]] = []
    for paragraph in paragraphs:
        sentences = _split_sentences(paragraph)
        start = len(all_sentences)
        all_sentences.extend(sentences)
        paragraph_ranges.append((start, len(all_sentences)))

    while len(all_sentences) > max_allowed:
        removed = False
        if all_sentences and (
            _rewrite_sentence_is_filler(all_sentences[0])
            or _rewrite_sentence_is_added(all_sentences[0], original)
        ):
            all_sentences.pop(0)
            removed = True
        elif all_sentences and (
            _rewrite_line_is_thanks_closing(all_sentences[-1])
            or _rewrite_sentence_is_added(all_sentences[-1], original)
        ):
            all_sentences.pop()
            removed = True
        if not removed:
            all_sentences.pop()

    if not all_sentences:
        return rewritten.strip()

    rebuilt: list[str] = []
    cursor = 0
    for start, end in paragraph_ranges:
        count = max(0, min(end, len(all_sentences)) - start)
        if count <= 0:
            continue
        chunk = all_sentences[cursor : cursor + count]
        cursor += count
        rebuilt.append(_join_sentences(chunk))
    if cursor < len(all_sentences):
        rebuilt.append(_join_sentences(all_sentences[cursor:]))
    return "\n\n".join(part for part in rebuilt if part.strip()).strip()


def _fix_rewrite_exclamation_marks(original: str, rewritten: str) -> str:
    if "!" in original:
        return rewritten
    result = rewritten.replace("!", ".")
    result = re.sub(r"\.{2,}", ".", result)
    result = re.sub(r"\.\s+\.", ".", result)
    return result


def _fix_rewrite_leading_artifacts(text: str) -> str:
    return re.sub(r"^[\s.,;:!?\-–—]+", "", text).strip()


def apply_rewrite_hard_filters(original: str, rewritten: str) -> str:
    if not rewritten or not original:
        return rewritten

    source = original.strip()
    result = rewritten.strip()
    result = _remove_added_greeting_signoff_lines(source, result)
    result = _remove_added_content_lines(source, result)
    result = _remove_added_filler_sentences(source, result)
    result = _strip_added_thanks_closing(source, result)
    result = _strip_excess_rewrite_sentences(source, result)
    result = _fix_rewrite_exclamation_marks(source, result)
    result = _fix_rewrite_leading_artifacts(result)
    return result.strip()


_GREETING_LINE_RE = re.compile(r"^(Dear|Hi|Hey|Hello)\b", re.IGNORECASE)
_SIGNOFF_LINE_RE = re.compile(
    r"^(Sincerely|Best|Thanks|Thank you|Regards|Kind regards|Warm regards|Cheers|Take care)\b",
    re.IGNORECASE,
)

_HOPE_DOING_WELL_RE = re.compile(
    r"\b(?:i\s+)?hope\s+you(?:'re|are)\s+doing\s+well\b",
    re.IGNORECASE,
)
_HOPE_FINDS_WELL_RE = re.compile(
    r"\b(?:i\s+)?hope\s+this(?:\s+email)?\s+finds\s+you\s+well\b",
    re.IGNORECASE,
)
_FRIENDLY_ALLOWED_OPENER_RE = re.compile(
    r"^hope\s+you(?:'re|are)\s+having\s+a\s+good\s+one[.!]?\s*$",
    re.IGNORECASE,
)

_SHORT_WARMUP_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^(?:i\s+)?hope\b", re.IGNORECASE),
    re.compile(r"^hope\s+you", re.IGNORECASE),
    re.compile(r"^thank you for\b", re.IGNORECASE),
    re.compile(r"^thanks for\b", re.IGNORECASE),
    re.compile(r"^i(?:'m| am) writing to\b", re.IGNORECASE),
    re.compile(r"^i wanted to reach out\b", re.IGNORECASE),
    re.compile(r"^just (?:wanted to|checking in)\b", re.IGNORECASE),
    re.compile(r"^i am reaching out\b", re.IGNORECASE),
    re.compile(r"^good (?:morning|afternoon|evening)\b", re.IGNORECASE),
)

_FORMAL_POLITE_OPENER_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^i hope\b", re.IGNORECASE),
    re.compile(r"^i trust\b", re.IGNORECASE),
    re.compile(r"^i hope this\b", re.IGNORECASE),
)

_SIMPLE_COMPLEXITY_REPLACEMENTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bI am writing to request\b", re.IGNORECASE), "I wanted to ask"),
    (re.compile(r"\bI am writing to ask\b", re.IGNORECASE), "I wanted to ask"),
    (re.compile(r"\bI am writing to inform you that\b", re.IGNORECASE), ""),
    (re.compile(r"\bI am writing to\b", re.IGNORECASE), "I need to"),
    (re.compile(r"\bI would like to inquire\b", re.IGNORECASE), "I wanted to ask"),
    (re.compile(r"\bI would like to request\b", re.IGNORECASE), "can I get"),
    (re.compile(r"\bI would like to ask\b", re.IGNORECASE), "I wanted to ask"),
    (re.compile(r"\bI would like to know\b", re.IGNORECASE), "I wanted to know"),
    (re.compile(r"\bI hope this finds you well[.!,]?\s*", re.IGNORECASE), ""),
    (re.compile(r"\bPlease be advised that\b", re.IGNORECASE), ""),
    (re.compile(r"\bI am reaching out to\b", re.IGNORECASE), "I wanted to"),
    (re.compile(r"\bin order to\b", re.IGNORECASE), "to"),
    (re.compile(r"\butilize\b", re.IGNORECASE), "use"),
    (re.compile(r"\bcommence\b", re.IGNORECASE), "start"),
    (re.compile(r"\bfacilitate\b", re.IGNORECASE), "help"),
    (re.compile(r"\bexpedite\b", re.IGNORECASE), "speed up"),
    (re.compile(r"\bcomprehensive\b", re.IGNORECASE), "full"),
    (re.compile(r"\bendeavor\b", re.IGNORECASE), "try"),
    (re.compile(r"\bsubsequently\b", re.IGNORECASE), "then"),
    (re.compile(r"\bprior to\b", re.IGNORECASE), "before"),
    (re.compile(r"\bregarding\b", re.IGNORECASE), "about"),
    (re.compile(r"\bpursuant to\b", re.IGNORECASE), "under"),
    (re.compile(r"\bat this point in time\b", re.IGNORECASE), "now"),
    (re.compile(r"\bwith regard to\b", re.IGNORECASE), "about"),
    (re.compile(r"\bin regard to\b", re.IGNORECASE), "about"),
    (re.compile(r"\bkindly\b", re.IGNORECASE), "please"),
    (re.compile(r"\bIs it possible for me to\b", re.IGNORECASE), "Can I"),
    (re.compile(r"\bI am writing regarding\b", re.IGNORECASE), "I'm asking about"),
    (re.compile(r"\bextended until\b", re.IGNORECASE), "pushed to"),
    (re.compile(r"\bhas been extended until\b", re.IGNORECASE), "got pushed to"),
    (re.compile(r"\bhas been extended\b", re.IGNORECASE), "got pushed"),
    (
        re.compile(r"\bdue to additional client requests for revisions\b", re.IGNORECASE),
        "because the client asked for more changes",
    ),
    (re.compile(r"\badditional client requests for revisions\b", re.IGNORECASE), "the client asking for more changes"),
    (re.compile(r"\bclient requests for revisions\b", re.IGNORECASE), "the client asking for more changes"),
    (re.compile(r"\brequests for revisions\b", re.IGNORECASE), "asks for more changes"),
    (re.compile(r"\bdue to additional\b", re.IGNORECASE), "because of"),
    (re.compile(r"\bat this time\b", re.IGNORECASE), "now"),
    (re.compile(r"\bregarding\b", re.IGNORECASE), "about"),
    (re.compile(r"\bI would appreciate\b", re.IGNORECASE), "I'd like"),
    (re.compile(r"\bwould appreciate\b", re.IGNORECASE), "would like"),
    (re.compile(r"\bsubmit your updates\b", re.IGNORECASE), "send your updates"),
    (re.compile(r"\bprior to\b", re.IGNORECASE), "before"),
    (re.compile(r"\bsubsequently\b", re.IGNORECASE), "then"),
    (re.compile(r"\badditional\b", re.IGNORECASE), "more"),
    (re.compile(r"\brevisions\b", re.IGNORECASE), "changes"),
)


def _split_sentences(text: str) -> list[str]:
    if not text or not text.strip():
        return []
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [part.strip() for part in parts if part.strip()]


def _join_sentences(sentences: list[str]) -> str:
    return " ".join(sentence.strip() for sentence in sentences if sentence.strip())


def _sentence_is_short_warmup(sentence: str) -> bool:
    stripped = sentence.strip()
    if not stripped:
        return True
    return any(pattern.search(stripped) for pattern in _SHORT_WARMUP_PATTERNS)


def _sentence_is_formal_polite_opener(sentence: str) -> bool:
    stripped = sentence.strip()
    return any(pattern.search(stripped) for pattern in _FORMAL_POLITE_OPENER_PATTERNS)


def _clean_hope_banned_sentence(sentence: str, *, allow_good_one: bool) -> str | None:
    if allow_good_one and _FRIENDLY_ALLOWED_OPENER_RE.match(sentence.strip()):
        return sentence
    cleaned = _HOPE_DOING_WELL_RE.sub("", sentence)
    cleaned = _HOPE_FINDS_WELL_RE.sub("", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" ,;")
    if not cleaned or re.fullmatch(r"[,.\s!?]+", cleaned):
        return None
    return cleaned


def _strip_friendly_casual_hope_phrases(text: str, *, allow_good_one: bool) -> str:
    paragraphs = re.split(r"\n\s*\n", text)
    filtered_paragraphs: list[str] = []
    for paragraph in paragraphs:
        sentences = _split_sentences(paragraph)
        kept: list[str] = []
        for sentence in sentences:
            cleaned = _clean_hope_banned_sentence(sentence, allow_good_one=allow_good_one)
            if cleaned:
                kept.append(cleaned)
        if kept:
            filtered_paragraphs.append(_join_sentences(kept))
    return "\n\n".join(filtered_paragraphs)


def _strip_leading_warmup_sentences(
    sentences: list[str],
    *,
    tone_preset: str,
    length: str,
) -> list[str]:
    if not sentences:
        return sentences
    remaining = list(sentences)
    allow_good_one = (
        tone_preset == "friendly" and length in {"medium", "long"} and len(remaining) > 0
    )
    if allow_good_one and _FRIENDLY_ALLOWED_OPENER_RE.match(remaining[0].strip()):
        return remaining

    while remaining:
        first = remaining[0].strip()
        if length == "short" and _sentence_is_short_warmup(first):
            remaining.pop(0)
            continue
        if tone_preset in {"friendly", "casual"} and (
            _HOPE_DOING_WELL_RE.search(first) or _HOPE_FINDS_WELL_RE.search(first)
        ):
            remaining.pop(0)
            continue
        if length == "short" and tone_preset == "formal" and _sentence_is_formal_polite_opener(first):
            remaining.pop(0)
            continue
        break
    return remaining


def _trim_formal_body_openers(sentences: list[str]) -> list[str]:
    if not sentences:
        return sentences
    result: list[str] = []
    opener_kept = False
    for sentence in sentences:
        if _sentence_is_formal_polite_opener(sentence):
            if not opener_kept and len(sentence.split()) <= 15:
                result.append(sentence)
                opener_kept = True
            continue
        result.append(sentence)
    return result


def _filter_prose_block(
    text: str,
    *,
    tone_preset: str,
    length: str,
) -> str:
    paragraphs = [paragraph.strip() for paragraph in re.split(r"\n\s*\n", text) if paragraph.strip()]
    if not paragraphs:
        return text

    first_sentences = _split_sentences(paragraphs[0])
    if length == "short":
        first_sentences = _strip_leading_warmup_sentences(
            first_sentences, tone_preset=tone_preset, length=length
        )
    elif tone_preset == "formal" and length in {"medium", "long"}:
        first_sentences = _trim_formal_body_openers(first_sentences)
    elif tone_preset == "friendly" and length in {"medium", "long"}:
        first_sentences = _strip_leading_warmup_sentences(
            first_sentences, tone_preset=tone_preset, length=length
        )

    paragraphs[0] = _join_sentences(first_sentences)
    return "\n\n".join(paragraph for paragraph in paragraphs if paragraph.strip())


def _is_greeting_line(line: str) -> bool:
    return bool(_GREETING_LINE_RE.match(line.strip()))


def _is_signoff_line(line: str) -> bool:
    return bool(_SIGNOFF_LINE_RE.match(line.strip()))


def _parse_email_sections(text: str) -> dict[str, str]:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    prefix_lines: list[str] = []
    index = 0
    if lines and lines[0].lower().startswith("subject:"):
        prefix_lines.append(lines[0])
        index = 1
    while index < len(lines) and not lines[index].strip():
        index += 1

    remaining = lines[index:]
    if not remaining:
        return {
            "prefix": "\n".join(prefix_lines),
            "greeting": "",
            "body": "",
            "footer": "",
        }

    greeting = ""
    body_start = 0
    if _is_greeting_line(remaining[0]):
        greeting = remaining[0]
        body_start = 1

    footer_start = len(remaining)
    for line_index in range(len(remaining) - 1, -1, -1):
        if _is_signoff_line(remaining[line_index]):
            footer_start = line_index
            break

    body = "\n".join(remaining[body_start:footer_start]).strip()
    footer = "\n".join(remaining[footer_start:]).strip()
    return {
        "prefix": "\n".join(prefix_lines),
        "greeting": greeting,
        "body": body,
        "footer": footer,
    }


def _reassemble_email_sections(sections: dict[str, str]) -> str:
    parts = [
        sections["prefix"],
        sections["greeting"],
        sections["body"],
        sections["footer"],
    ]
    return "\n\n".join(part for part in parts if part.strip())


def _filter_email_body(
    body: str,
    *,
    tone_preset: str,
    length: str,
) -> str:
    if not body.strip():
        return body

    paragraphs = [paragraph.strip() for paragraph in re.split(r"\n\s*\n", body) if paragraph.strip()]
    if not paragraphs:
        return body

    first_sentences = _split_sentences(paragraphs[0])
    if length == "short":
        first_sentences = _strip_leading_warmup_sentences(
            first_sentences, tone_preset=tone_preset, length=length
        )
    elif tone_preset == "formal" and length in {"medium", "long"}:
        first_sentences = _trim_formal_body_openers(first_sentences)
    elif tone_preset == "friendly" and length in {"medium", "long"}:
        first_sentences = _strip_leading_warmup_sentences(
            first_sentences, tone_preset=tone_preset, length=length
        )

    paragraphs[0] = _join_sentences(first_sentences)
    filtered_body = "\n\n".join(paragraph for paragraph in paragraphs if paragraph.strip())

    if tone_preset in {"friendly", "casual"}:
        allow_good_one = tone_preset == "friendly" and length in {"medium", "long"}
        filtered_body = _strip_friendly_casual_hope_phrases(
            filtered_body, allow_good_one=allow_good_one
        )

    return filtered_body


def _apply_simple_complexity_replacements(text: str) -> str:
    result = text
    for pattern, replacement in _SIMPLE_COMPLEXITY_REPLACEMENTS:
        result = pattern.sub(replacement, result)
    result = re.sub(r"  +", " ", result)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


def _take_first_complete_draft(text: str) -> str:
    if "\n---\n" in text:
        return text.split("\n---\n", 1)[0].strip()
    subject_matches = list(re.finditer(r"(?m)^Subject:", text))
    if len(subject_matches) > 1:
        return text[: subject_matches[1].start()].strip()
    return text.strip()


def _count_email_body_paragraphs(text: str) -> int:
    sections = _parse_email_sections(text)
    body = sections.get("body", "")
    if not body.strip():
        return 0
    return len([paragraph for paragraph in re.split(r"\n\s*\n", body) if paragraph.strip()])


def _count_body_sentences(text: str, format_type: str) -> int:
    if format_type == "email":
        body = _parse_email_sections(text).get("body", "")
    else:
        body = text
    if not body.strip():
        return 0
    return len([s for s in _split_sentences(body) if s.strip()])


def _meets_generate_length_requirement(text: str, format_type: str, length: str) -> bool:
    """Check body structure only — never inspect tone or vocabulary."""
    if format_type == "email":
        paragraph_count = _count_email_body_paragraphs(text)
        sentence_count = _count_body_sentences(text, format_type)
    else:
        paragraphs = [p for p in re.split(r"\n\s*\n", text or "") if p.strip()]
        paragraph_count = len(paragraphs)
        sentence_count = _count_body_sentences(text, format_type)

    if length == "short":
        # 1 short paragraph or 2–3 sentences; must have content, no padding
        return paragraph_count <= 1 and 1 <= sentence_count <= 3
    if length == "medium":
        return 2 <= paragraph_count <= 3
    if length == "long":
        return paragraph_count >= 4
    return True


def _enforce_length_structure(text: str, format_type: str, length: str) -> str:
    """Adjust paragraph/sentence count only — never rewrite words (tone/complexity stay)."""
    if not text or not text.strip():
        return text

    if format_type == "email":
        sections = _parse_email_sections(text)
        body = sections.get("body", "")
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]

        if length == "short":
            if not paragraphs:
                return text
            sentences = _split_sentences(paragraphs[0])[:3]
            if not sentences and paragraphs:
                sentences = [paragraphs[0]]
            sections["body"] = _join_sentences(sentences)
            return _reassemble_email_sections(sections)

        if length == "medium":
            if len(paragraphs) == 1:
                sentences = _split_sentences(paragraphs[0])
                if len(sentences) >= 2:
                    mid = max(1, len(sentences) // 2)
                    paragraphs = [
                        _join_sentences(sentences[:mid]),
                        _join_sentences(sentences[mid:]),
                    ]
            elif len(paragraphs) > 3:
                paragraphs = paragraphs[:2] + [" ".join(paragraphs[2:])]
            sections["body"] = "\n\n".join(paragraphs)
            return _reassemble_email_sections(sections)

        if length == "long":
            while len(paragraphs) < 4:
                best_i = -1
                best_sents: list[str] = []
                for index, paragraph in enumerate(paragraphs):
                    sentences = _split_sentences(paragraph)
                    if len(sentences) >= 2 and len(sentences) > len(best_sents):
                        best_i = index
                        best_sents = sentences
                if best_i < 0:
                    break
                mid = max(1, len(best_sents) // 2)
                paragraphs[best_i : best_i + 1] = [
                    _join_sentences(best_sents[:mid]),
                    _join_sentences(best_sents[mid:]),
                ]
            sections["body"] = "\n\n".join(paragraphs)
            return _reassemble_email_sections(sections)

        return text

    # Essay / prose
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if length == "short":
        if not paragraphs:
            return text
        return _join_sentences(_split_sentences(paragraphs[0])[:3])
    if length == "medium":
        if len(paragraphs) == 1:
            sentences = _split_sentences(paragraphs[0])
            if len(sentences) >= 2:
                mid = max(1, len(sentences) // 2)
                return "\n\n".join(
                    [_join_sentences(sentences[:mid]), _join_sentences(sentences[mid:])]
                )
        if len(paragraphs) > 3:
            return "\n\n".join(paragraphs[:2] + [" ".join(paragraphs[2:])])
        return text
    if length == "long":
        while len(paragraphs) < 4:
            best_i = -1
            best_sents = []
            for index, paragraph in enumerate(paragraphs):
                sentences = _split_sentences(paragraph)
                if len(sentences) >= 2 and len(sentences) > len(best_sents):
                    best_i = index
                    best_sents = sentences
            if best_i < 0:
                break
            mid = max(1, len(best_sents) // 2)
            paragraphs[best_i : best_i + 1] = [
                _join_sentences(best_sents[:mid]),
                _join_sentences(best_sents[mid:]),
            ]
        return "\n\n".join(paragraphs)
    return text


def _build_length_retry_instruction(length: str, format_type: str) -> str:
    kind = "email" if format_type == "email" else "essay"
    if length == "short":
        return (
            "LENGTH RETRY — previous draft was too long. "
            f"Output ONE {kind} only with 1 short body paragraph or 2–3 body sentences. "
            "Core message only, no padding. Do not change tone or vocabulary."
        )
    if length == "medium":
        return (
            "LENGTH RETRY — previous draft body had the wrong paragraph count. "
            f"Output ONE {kind} only with 2–3 body paragraphs separated by blank lines. "
            "Do not change tone or vocabulary."
        )
    return (
        "LENGTH RETRY — previous draft body had too few paragraphs. "
        f"Output ONE {kind} only with at least 4 body paragraphs of full detail. "
        "Do not change tone or vocabulary."
    )


_SHORT_SEED_STOPWORDS = frozenset(
    {
        "the", "a", "an", "to", "for", "and", "or", "my", "your", "our", "with", "about",
        "on", "in", "at", "is", "it", "be", "by", "of", "let", "know", "email", "team",
        "that", "this", "we", "you", "i", "me", "ask", "asking", "tell", "telling",
    }
)

_UNSEEDED_SHORT_ADDON_PHRASES: tuple[str, ...] = (
    "please review",
    "provide feedback",
    "let me know if",
    "feel free to",
    "do not hesitate",
    "any questions",
    "looking forward",
    "thank you for your",
    "please let me know",
    "review the changes",
    "share your thoughts",
    "provide an update",
    "confirm receipt",
    "reach out if",
    "further steps",
    "next steps",
    "your feedback",
    "if you have any questions",
    "don't hesitate",
    "please review changes",
    "provide feedback on",
)


def _seed_content_tokens(text: str) -> set[str]:
    return {
        word
        for word in re.findall(r"[a-z0-9']+", text.lower())
        if word not in _SHORT_SEED_STOPWORDS and len(word) > 2
    }


def _sentence_grounded_in_seed(sentence: str, seed_baseline: str) -> bool:
    seed_lower = seed_baseline.lower()
    sentence_lower = sentence.lower()
    for phrase in _UNSEEDED_SHORT_ADDON_PHRASES:
        if phrase in sentence_lower and phrase not in seed_lower:
            return False
    sentence_tokens = _seed_content_tokens(sentence)
    if not sentence_tokens:
        return True
    seed_tokens = _seed_content_tokens(seed_baseline)
    if not seed_tokens:
        return True
    overlap = len(sentence_tokens & seed_tokens) / len(sentence_tokens)
    return overlap >= 0.12


def _filter_short_body_to_seed(body: str, seed_baseline: str) -> str:
    if not body.strip() or not seed_baseline.strip():
        return body

    paragraphs = [paragraph.strip() for paragraph in re.split(r"\n\s*\n", body) if paragraph.strip()]
    if not paragraphs:
        return body

    sentences = _split_sentences(paragraphs[0])
    kept = [sentence for sentence in sentences if _sentence_grounded_in_seed(sentence, seed_baseline)]
    if not kept and sentences:
        kept = [sentences[0]]
    paragraphs[0] = _join_sentences(kept[:2])
    return "\n\n".join(paragraph for paragraph in paragraphs if paragraph.strip())


def _filter_short_to_seed_content(
    text: str,
    seed_baseline: str,
    *,
    format_type: str,
) -> str:
    if format_type == "email":
        sections = _parse_email_sections(text)
        sections["body"] = _filter_short_body_to_seed(sections["body"], seed_baseline)
        return _reassemble_email_sections(sections)

    paragraphs = [paragraph.strip() for paragraph in re.split(r"\n\s*\n", text) if paragraph.strip()]
    if not paragraphs:
        return text
    sentences = _split_sentences(paragraphs[0])
    kept = [sentence for sentence in sentences if _sentence_grounded_in_seed(sentence, seed_baseline)]
    if not kept and sentences:
        kept = [sentences[0]]
    paragraphs[0] = _join_sentences(kept[:2])
    return "\n\n".join(paragraph for paragraph in paragraphs if paragraph.strip())


def build_seed_content_baseline(text: str, notes: str = "") -> str:
    parsed = _parse_generation_note(notes)
    parts = [text.strip()]
    if parsed.get("informational_content"):
        parts.append(parsed["informational_content"].strip())
    return " ".join(part for part in parts if part)


def apply_generate_hard_filters(
    text: str,
    *,
    format_type: str,
    settings: dict[str, Any] | None,
    seed_baseline: str = "",
) -> str:
    if not text or not text.strip():
        return text

    normalized = _normalize_generate_settings(settings)
    tone_preset = normalized["tone_preset"]
    length = normalized["length"]
    complexity = normalized["complexity"]

    filtered = text
    if tone_preset in {"friendly", "casual"}:
        # Tone-only cleanup — never depends on length setting
        filtered = _strip_friendly_casual_hope_phrases(filtered, allow_good_one=False)

    if format_type == "email":
        sections = _parse_email_sections(filtered)
        sections["body"] = _filter_email_body(
            sections["body"],
            tone_preset=tone_preset,
            length=length,
        )
        sections["greeting"] = _enforce_tone_greeting_line(
            sections.get("greeting", ""), tone_preset
        )
        sections["footer"] = _enforce_tone_signoff(
            sections.get("footer", ""), tone_preset, normalized.get("profile") or {}
        )
        filtered = _reassemble_email_sections(sections)
    else:
        filtered = _filter_prose_block(filtered, tone_preset=tone_preset, length=length)

    if tone_preset == "formal":
        filtered = _apply_formal_tone_voice(filtered)

    if complexity == "simple":
        filtered = _apply_simple_complexity_replacements(filtered)

    if length == "short" and seed_baseline.strip():
        filtered = _filter_short_to_seed_content(
            filtered,
            seed_baseline,
            format_type=format_type,
        )

    filtered = _normalize_generate_names(filtered, normalized.get("profile") or {})
    filtered = _take_first_complete_draft(filtered)

    return filtered


def _enforce_tone_greeting_line(greeting: str, tone_preset: str) -> str:
    """Force greeting prefix by tone only — no placeholder brackets."""
    stripped = (greeting or "").strip()
    name = ""
    match = _GREETING_WITH_NAME_RE.match(stripped) if stripped else None
    if match:
        name = match.group(2).strip().rstrip(",")
        if name in ("[Name]", "[Your Name]", "Name", "Your Name"):
            name = ""
        elif name.startswith("[") and name.endswith("]"):
            name = ""
    elif stripped and not re.match(r"^(Dear|Hi|Hey|Hello)\b", stripped, re.I):
        name = stripped.rstrip(",")
    prefix = {"formal": "Dear", "friendly": "Hi", "casual": "Hey"}.get(
        tone_preset, "Hi"
    )
    if name:
        return f"{prefix} {name}"
    if tone_preset == "formal":
        return "Hello"
    if tone_preset == "casual":
        return "Hey"
    return "Hi"


def _enforce_tone_signoff(
    footer: str, tone_preset: str, profile: dict[str, Any]
) -> str:
    """Force sign-off word by tone only — no placeholder brackets."""
    saved_name = _extract_profile_full_name(profile)
    lines = [ln.strip() for ln in (footer or "").split("\n") if ln.strip()]
    name = saved_name
    if not name and len(lines) >= 2:
        candidate = lines[-1]
        if (
            candidate not in ("[Name]", "[Your Name]", "Name", "Your Name")
            and not (candidate.startswith("[") and candidate.endswith("]"))
            and not _is_signoff_line(candidate)
        ):
            name = candidate
    elif not name and lines and not _is_signoff_line(lines[0]):
        candidate = lines[0]
        if candidate not in ("[Name]", "[Your Name]") and not (
            candidate.startswith("[") and candidate.endswith("]")
        ):
            name = candidate
    # Prefer saved sign-off from profile when present
    preferred = str(
        profile.get("signOff") or profile.get("sign_off") or ""
    ).strip()
    if preferred:
        signoff = preferred if preferred.endswith((",", "!")) else f"{preferred},"
    else:
        signoff = {"formal": "Sincerely,", "friendly": "Best,", "casual": "Thanks,"}.get(
            tone_preset, "Best,"
        )
    if name:
        return f"{signoff}\n{name}"
    return signoff


_GREETING_WITH_NAME_RE = re.compile(
    r"^(Dear|Hi|Hey|Hello)\s+(.+)$",
    re.IGNORECASE,
)

_SIGNOFF_INLINE_NAME_RE = re.compile(
    r"^((?:Best|Thanks|Thank you|Sincerely|Regards),?)\s+([A-Z][^\n]+)$",
    re.IGNORECASE,
)


def _extract_profile_full_name(profile: dict[str, Any]) -> str:
    return str(profile.get("fullName") or profile.get("full_name") or "").strip()


def _is_placeholder_name(value: str) -> bool:
    text = (value or "").strip()
    if not text:
        return True
    if text in ("[Name]", "[Your Name]", "Name", "Your Name"):
        return True
    return bool(re.fullmatch(r"\[[^\]]+\]", text))


def _normalize_generate_names(text: str, profile: dict[str, Any]) -> str:
    if not text or not text.strip():
        return text

    saved_name = _extract_profile_full_name(profile)
    # Strip any leftover placeholder brackets from the model
    text = re.sub(r"\[Your Name\]", saved_name or "", text)
    text = re.sub(r"\[Name\]", "", text)
    text = re.sub(r" {2,}", " ", text)

    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    normalized_lines: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            normalized_lines.append(line)
            continue

        greeting_match = _GREETING_WITH_NAME_RE.match(stripped)
        if greeting_match:
            prefix = greeting_match.group(1)
            name_part = greeting_match.group(2).strip().rstrip(",")
            if _is_placeholder_name(name_part):
                normalized_lines.append(prefix)
                continue
            if saved_name and name_part.lower() == saved_name.lower():
                normalized_lines.append(line)
                continue
            # Drop invented recipient names — keep generic greeting only
            normalized_lines.append(prefix)
            continue

        signoff_match = _SIGNOFF_INLINE_NAME_RE.match(stripped)
        if signoff_match:
            prefix = signoff_match.group(1)
            name_part = signoff_match.group(2).strip()
            if _is_placeholder_name(name_part):
                normalized_lines.append(prefix if prefix.endswith(",") else f"{prefix},")
                continue
            if saved_name and name_part.lower() == saved_name.lower():
                normalized_lines.append(line)
                continue
            if saved_name:
                normalized_lines.append(f"{prefix} {saved_name}")
            else:
                normalized_lines.append(prefix if prefix.endswith(",") else f"{prefix},")
            continue

        if _is_placeholder_name(stripped):
            if saved_name:
                normalized_lines.append(saved_name)
            # else drop the placeholder line entirely
            continue

        normalized_lines.append(line)

    result = "\n".join(normalized_lines)
    result_lines = result.split("\n")
    for index in range(len(result_lines) - 1):
        current = result_lines[index].strip()
        nxt = result_lines[index + 1].strip()
        if not _is_signoff_line(current) or not nxt:
            continue
        if _is_placeholder_name(nxt):
            result_lines[index + 1] = saved_name if saved_name else ""
            continue
        if saved_name and nxt.lower() == saved_name.lower():
            continue
        if re.fullmatch(r"[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?", nxt):
            # Drop invented sender names when no profile is saved
            result_lines[index + 1] = saved_name if saved_name else ""

    return "\n".join(line for line in result_lines if line is not None)


def format_document_context(context: dict[str, Any] | None) -> str:
    if not context:
        return ""

    lines: list[str] = ["DOCUMENT CONTEXT:"]

    page = context.get("page") or {}
    if page:
        lines.append(f"- Application: {page.get('app') or 'unknown'}")
        lines.append(f"- Document type: {page.get('documentType') or 'unknown'}")
        if page.get("title"):
            lines.append(f"- Page title: {page['title']}")

    field = context.get("field") or {}
    if field:
        lines.append(f"- Field role: {field.get('role') or 'unknown'}")
        if field.get("label"):
            lines.append(f"- Field label: {field['label']}")

    layout = context.get("layout") or {}
    if layout:
        lines.append(f"- Block type: {layout.get('blockType') or 'unknown'}")
        if layout.get("inList"):
            lines.append(
                f"- Inside list ({layout.get('listType') or 'list'} item "
                f"{layout.get('listIndex') or '?'})"
            )
        if layout.get("paragraphIndex") is not None:
            lines.append(
                f"- Paragraph {layout['paragraphIndex']} of "
                f"{layout.get('paragraphCount') or '?'}"
            )

    selection = context.get("selection") or {}
    if selection.get("wordCount") is not None:
        lines.append(f"- Selection length: {selection['wordCount']} words")

    surrounding = context.get("surrounding") or {}
    if surrounding.get("before"):
        lines.append(f"\nTEXT BEFORE SELECTION:\n...{surrounding['before']}")
    if surrounding.get("after"):
        lines.append(f"\nTEXT AFTER SELECTION:\n{surrounding['after']}...")

    return "\n".join(lines)


def _normalize_tone_instruction(instruction: str) -> str:
    text = (instruction or "").strip()
    if not text:
        text = "Rewrite to sound clear and natural."
    lower = text.lower()
    if "return only" not in lower and "nothing else" not in lower:
        if not text.endswith((".", "!", "?")):
            text += "."
        text += TONE_REWRITE_OUTPUT_RULE
    return text.strip()


def build_rewrite_prompt(
    text: str,
    user_instruction: str,
    context: dict[str, Any] | None = None,
    *,
    direct: bool = False,
) -> str:
    instruction = (user_instruction or "").strip()
    context_block = format_document_context(context)

    if direct:
        tone_instruction = _normalize_tone_instruction(instruction)
        sections: list[str] = [TONE_REWRITE_STRICT_RULES]
        if context_block:
            sections.append(context_block)
        sections.append(f"USER INSTRUCTION:\n{tone_instruction}\n\nSELECTED TEXT TO REWRITE:\n{text}")
        return "\n\n".join(sections)

    if not instruction:
        instruction = "Rewrite to sound clear and natural."
    elif len(instruction.split()) <= 2 and not any(
        char in instruction for char in ".!?,:;"
    ):
        instruction = f"Rewrite in a {instruction} tone."
    elif not instruction.lower().startswith("rewrite"):
        instruction = f"Rewrite the text as follows: {instruction}"

    planning = (
        "TASK: REWRITE the selected passage.\n"
        "1. Read document context and surrounding text.\n"
        "2. Rewrite ONLY the selection — not text before or after.\n"
        "3. Change word choice and sentence structure only to match the requested tone.\n"
        "4. Keep the same information and roughly the same length — do not add or remove content.\n"
        "5. Fit the layout: list items stay parallel; preserve existing line structure.\n\n"
        f"{TONE_REWRITE_STRICT_RULES}\n\n"
        "OUTPUT: Return the COMPLETE rewritten selection as plain text only. "
        "No diffs, labels, or partial edits."
    )

    sections = [planning]
    if context_block:
        sections.append(context_block)
    sections.append(f"\nUSER INSTRUCTION:\n{instruction}")
    sections.append(f"\nSELECTED TEXT TO REWRITE:\n{text}")
    return "\n\n".join(sections)


def _normalize_generate_settings(
    settings: dict[str, Any] | None,
) -> dict[str, Any]:
    raw = settings or {}
    tone_preset = str(raw.get("tone_preset") or raw.get("tonePreset") or "friendly").strip().lower()
    if tone_preset not in TONE_PRESET_GUIDANCE:
        tone_preset = "friendly"
    tone = str(raw.get("tone") or TONE_PRESET_TO_VOICE.get(tone_preset, "warm and friendly")).strip()
    length = str(raw.get("length") or "medium").strip().lower()
    if length not in GENERATE_LENGTH_GUIDANCE:
        length = "medium"
    complexity = str(raw.get("complexity") or raw.get("wording") or "standard").strip().lower()
    if complexity not in GENERATE_COMPLEXITY_GUIDANCE:
        complexity = "standard"
    include_subject = raw.get("include_subject")
    if include_subject is None:
        include_subject = raw.get("includeSubject", True)
    profile = raw.get("profile")
    if not isinstance(profile, dict):
        profile = {}
    return {
        "tone": tone,
        "tone_preset": tone_preset,
        "length": length,
        "complexity": complexity,
        "include_subject": bool(include_subject),
        "profile": profile,
    }


NOTE_INFORMATIONAL_RULES = """\
INFORMATIONAL NOTE — content only (does NOT change tone or style):
  • Add the facts below into the generated text naturally.
  • Do NOT change tone, greeting, sign-off, complexity, length, or add filler phrases.
  • Do NOT reinterpret this note as a style or tone instruction.
  • Saved tone, length, and complexity settings control how it sounds — this note only adds what is said."""

NOTE_TONE_OVERRIDE_RULES = """\
ONE-TIME TONE OVERRIDE — this generation only (saved popup tone is unchanged for next time):
  • Ignore the saved tone setting for THIS generation only.
  • Apply the tone instruction below to greeting, body phrasing, subject, and sign-off.
  • Length and complexity settings still apply unchanged.
  • The SEED TEXT defines WHAT to say — you MUST fully expand it into the complete email body.
  • Tone changes HOW it sounds only — never skip, shorten, or replace the seed topic.
  • If the seed says "asking for an extension", the body MUST explicitly request an extension.
  • Do not treat any other part of the user note as a tone instruction."""

_TONE_INSTRUCTION_MAPPINGS: tuple[tuple[re.Pattern[str], str, str | None], ...] = (
    (re.compile(r"\bmake it (?:more )?formal(?:\s+than\s+usual)?\b", re.IGNORECASE), "formal", None),
    (re.compile(r"\b(?:sound|be) more formal(?:\s+than\s+usual)?\b", re.IGNORECASE), "formal", None),
    (re.compile(r"\bmake it (?:more )?professional\b", re.IGNORECASE), "formal", "professional and respectful"),
    (re.compile(r"\b(?:sound|be) more professional\b", re.IGNORECASE), "formal", "professional and respectful"),
    (re.compile(r"\bkeep it professional\b", re.IGNORECASE), "formal", "professional and respectful"),
    (re.compile(r"\bmake it (?:more )?friendly\b", re.IGNORECASE), "friendly", None),
    (re.compile(r"\b(?:sound|be) more friendly\b", re.IGNORECASE), "friendly", None),
    (re.compile(r"\bsound more friendly\b", re.IGNORECASE), "friendly", None),
    (re.compile(r"\bmake it (?:more )?casual\b", re.IGNORECASE), "casual", None),
    (re.compile(r"\b(?:sound|be) more casual\b", re.IGNORECASE), "casual", None),
    (re.compile(r"\bkeep it (?:casual|conversational)\b", re.IGNORECASE), "casual", None),
    (re.compile(r"\bkeep it conversational\b", re.IGNORECASE), "casual", "relaxed and conversational"),
    (re.compile(r"\bmake it (?:more )?conversational\b", re.IGNORECASE), "casual", "relaxed and conversational"),
    (re.compile(r"\bmake it funnier\b", re.IGNORECASE), "casual", "humorous and conversational"),
    (re.compile(r"\bmake it (?:more )?humorous\b", re.IGNORECASE), "casual", "humorous and conversational"),
    (re.compile(r"\bmake it (?:more )?warm\b", re.IGNORECASE), "friendly", "warm and approachable"),
    (re.compile(r"\b(?:sound|be) (?:more )?warm(?:er)?\b", re.IGNORECASE), "friendly", "warm and approachable"),
    (re.compile(r"\bmake it (?:more )?informal\b", re.IGNORECASE), "casual", None),
    (re.compile(r"\bmake it (?:more )?relaxed\b", re.IGNORECASE), "casual", None),
    (re.compile(r"\buse a (?:more )?formal tone\b", re.IGNORECASE), "formal", None),
    (re.compile(r"\buse a (?:more )?friendly tone\b", re.IGNORECASE), "friendly", None),
    (re.compile(r"\buse a (?:more )?casual tone\b", re.IGNORECASE), "casual", None),
    (re.compile(r"\bwrite (?:this |it )?(?:more )?formally\b", re.IGNORECASE), "formal", None),
    (re.compile(r"\bwrite (?:this |it )?(?:more )?casually\b", re.IGNORECASE), "casual", None),
)

_GENERIC_TONE_INSTRUCTION_RE = re.compile(
    r"\b(?:"
    r"(?:make|keep) it (?:more |less )?[a-z]+(?:\s+[a-z]+)?"
    r"|(?:sound|be) more [a-z]+"
    r"|use a (?:more )?[a-z]+ tone"
    r"|write (?:this |it )?(?:in a )?(?:more )?[a-z]+ (?:tone|way)"
    r"|(?:tone|style)\s*:\s*[^\n.]+"
    r")\b",
    re.IGNORECASE,
)

_TONE_STYLE_KEYWORDS = frozenset(
    {
        "formal",
        "informal",
        "professional",
        "casual",
        "friendly",
        "conversational",
        "funny",
        "funnier",
        "humorous",
        "warm",
        "warmer",
        "polite",
        "relaxed",
        "playful",
        "serious",
        "direct",
        "tone",
        "style",
    }
)

_NON_TONE_STYLE_WORDS = frozenset(
    {
        "clear",
        "specific",
        "sure",
        "brief",
        "short",
        "shorter",
        "long",
        "longer",
        "concise",
        "detailed",
        "accurate",
        "complete",
    }
)


def _cleanup_note_remainder(text: str) -> str:
    cleaned = text.strip()
    cleaned = re.sub(r"^[\s,.\-–—]+", "", cleaned)
    cleaned = re.sub(r"[\s,.\-–—]+$", "", cleaned)
    cleaned = re.sub(r"^(?:and|but|also)\s+", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+(?:and|but|also)$", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^than\s+(?:usual|normal)\.?$", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


def _looks_like_tone_style_instruction(phrase: str) -> bool:
    lower = phrase.lower()
    if any(word in lower for word in _NON_TONE_STYLE_WORDS):
        if not any(word in lower for word in _TONE_STYLE_KEYWORDS):
            return False
    return any(word in lower for word in _TONE_STYLE_KEYWORDS)


def _infer_tone_from_instruction(phrase: str) -> tuple[str, str | None]:
    lower = phrase.lower()
    if any(word in lower for word in ("formal", "professional", "business", "academic")):
        voice = "professional and respectful" if "professional" in lower else None
        return "formal", voice
    if any(word in lower for word in ("casual", "conversational", "informal", "relaxed")):
        voice = "relaxed and conversational" if "conversational" in lower else None
        return "casual", voice
    if any(word in lower for word in ("friendly", "warm", "approachable")):
        voice = "warm and approachable" if "warm" in lower else None
        return "friendly", voice
    if any(word in lower for word in ("funny", "funnier", "humorous", "playful")):
        return "casual", "humorous and conversational"
    return "friendly", phrase.strip()


def _parse_generation_note(notes: str) -> dict[str, Any]:
    raw = (notes or "").strip()
    if not raw:
        return {
            "tone_instruction": None,
            "tone_preset_override": None,
            "tone_voice_override": None,
            "informational_content": None,
            "has_tone_instruction": False,
        }

    remaining = raw
    tone_instruction: str | None = None
    tone_preset_override: str | None = None
    tone_voice_override: str | None = None

    for pattern, preset, voice in _TONE_INSTRUCTION_MAPPINGS:
        match = pattern.search(remaining)
        if not match:
            continue
        tone_instruction = match.group(0).strip()
        tone_preset_override = preset
        tone_voice_override = voice
        remaining = _cleanup_note_remainder(remaining[: match.start()] + remaining[match.end() :])
        break

    if tone_instruction is None:
        match = _GENERIC_TONE_INSTRUCTION_RE.search(remaining)
        if match and _looks_like_tone_style_instruction(match.group(0)):
            tone_instruction = match.group(0).strip()
            tone_preset_override, tone_voice_override = _infer_tone_from_instruction(tone_instruction)
            remaining = _cleanup_note_remainder(remaining[: match.start()] + remaining[match.end() :])

    informational_content = remaining.strip() or None
    return {
        "tone_instruction": tone_instruction,
        "tone_preset_override": tone_preset_override,
        "tone_voice_override": tone_voice_override,
        "informational_content": informational_content,
        "has_tone_instruction": tone_instruction is not None,
    }


def resolve_effective_generate_settings(
    settings: dict[str, Any] | None,
    notes: str = "",
) -> dict[str, Any]:
    effective = dict(_normalize_generate_settings(settings))
    parsed = _parse_generation_note(notes)
    if parsed["tone_preset_override"]:
        effective["tone_preset"] = parsed["tone_preset_override"]
        if parsed["tone_voice_override"]:
            effective["tone"] = parsed["tone_voice_override"]
        else:
            effective["tone"] = TONE_PRESET_TO_VOICE.get(
                parsed["tone_preset_override"],
                effective["tone"],
            )
    return effective


def _extract_permanent_note(profile: dict[str, Any]) -> str:
    return str(
        profile.get("permanentNote")
        or profile.get("permanent_note")
        or profile.get("permanentNotes")
        or profile.get("permanent_notes")
        or ""
    ).strip()


def _format_generate_profile(profile: dict[str, Any]) -> str:
    """Format profile as comma-separated key-value pairs for prompt injection."""
    labels = {
        "fullName": "full name",
        "full_name": "full name",
        "signOff": "preferred sign-off",
        "sign_off": "preferred sign-off",
        "jobTitle": "job title",
        "job_title": "job title",
        "companyName": "company name",
        "company_name": "company name",
        "schoolName": "school name",
        "school_name": "school name",
        "email": "email",
        "phone": "phone",
    }
    pairs: list[str] = []
    seen_labels: set[str] = set()
    for key, label in labels.items():
        if label in seen_labels:
            continue
        value = str(profile.get(key) or "").strip()
        if value:
            pairs.append(f"{label}={value}")
            seen_labels.add(label)
    if not pairs:
        return ""
    return (
        "PERSONAL PROFILE (comma-separated key-value pairs — auto-inject; "
        "reference name, role, or other details without the user typing them):\n"
        + ", ".join(pairs)
        + "\nUse the saved full name on the sign-off line. "
        "If a preferred sign-off is saved, use that exact line. "
        "Never invent names. Never output placeholder brackets."
    )


def _build_length_rules(length: str) -> str:
    return GENERATE_LENGTH_GUIDANCE.get(length, GENERATE_LENGTH_GUIDANCE["medium"])


def _build_tone_rules(tone_preset: str, format_type: str) -> str:
    tone = TONE_PRESET_GUIDANCE.get(tone_preset, TONE_PRESET_GUIDANCE["friendly"])
    parts = [tone, TONE_BANNED_FILLER_PHRASES]
    if format_type == "email":
        parts.append(TONE_EMAIL_CONVENTIONS.get(tone_preset, ""))
    else:
        parts.append(
            "ESSAY TONE: Apply the selected tone to every paragraph equally. "
            "TONE does not control how many paragraphs — LENGTH does."
        )
    return "\n\n".join(part for part in parts if part)


def _build_complexity_rules(complexity: str) -> str:
    return GENERATE_COMPLEXITY_GUIDANCE.get(
        complexity, GENERATE_COMPLEXITY_GUIDANCE["standard"]
    )


def _build_generate_system_prompt(
    length: str,
    complexity: str,
    tone_preset: str = "friendly",
    *,
    format_type: str = "email",
) -> str:
    parts = [
        WRITING_AGENT_SYSTEM_PROMPT,
        GENERATE_INDEPENDENCE_RULES,
        "=== LENGTH INSTRUCTION (structure only) ===",
        _build_length_rules(length),
        "=== TONE INSTRUCTION (voice only) ===",
        _build_tone_rules(tone_preset, format_type),
        "=== COMPLEXITY INSTRUCTION (vocabulary only) ===",
        _build_complexity_rules(complexity),
        GENERATE_STRICT_RULES,
    ]
    if length == "short":
        parts.append(GENERATE_SHORT_CONTENT_RULES)
    return "\n\n".join(parts)


def _generate_num_predict_for_length(length: str) -> int:
    if length == "long":
        return OLLAMA_GENERATE_NUM_PREDICT_LONG
    if length == "medium":
        return OLLAMA_GENERATE_NUM_PREDICT_MEDIUM
    return OLLAMA_GENERATE_NUM_PREDICT


def _build_generate_settings_block(
    tone_preset: str,
    length: str,
    complexity: str,
    format_type: str,
) -> str:
    # Three separate instructions — never merged into one combined instruction.
    return "\n\n".join(
        [
            GENERATE_INDEPENDENCE_RULES,
            "=== LENGTH INSTRUCTION (structure only) ===",
            _build_length_rules(length),
            "=== TONE INSTRUCTION (voice only) ===",
            _build_tone_rules(tone_preset, format_type),
            "=== COMPLEXITY INSTRUCTION (vocabulary only) ===",
            _build_complexity_rules(complexity),
            GENERATE_STRICT_RULES,
        ]
    )


def build_generate_prompt(
    text: str,
    format_type: str,
    notes: str = "",
    context: dict[str, Any] | None = None,
    settings: dict[str, Any] | None = None,
) -> str:
    format_type = (format_type or "essay").strip().lower()
    user_notes = (notes or "").strip()
    parsed_note = _parse_generation_note(user_notes)
    context_block = format_document_context(context)
    saved_settings = _normalize_generate_settings(settings)
    effective_settings = resolve_effective_generate_settings(settings, user_notes)
    tone_preset = effective_settings["tone_preset"]
    length = effective_settings["length"]
    complexity = effective_settings["complexity"]
    include_subject = effective_settings["include_subject"]
    profile = effective_settings["profile"]
    permanent_note = _extract_permanent_note(profile)
    profile_block = _format_generate_profile(profile)

    settings_block = _build_generate_settings_block(
        tone_preset, length, complexity, format_type
    )

    if format_type == "email":
        subject_rule = (
            'Include a subject line on the first line ("Subject: ..."). '
            "Subject wording follows TONE only; length of subject does not change BODY structure."
            if include_subject
            else "Do not include a subject line."
        )
        format_rules = f"{EMAIL_GENERATION_GUIDE}\n\n{settings_block}\n\n{subject_rule}"
    else:
        format_rules = (
            "TASK: GENERATE a complete essay from the seed below.\n"
            "- Replace the seed entirely with finished prose.\n"
            f"\n{settings_block}"
        )

    sections = [
        format_rules,
        "OUTPUT: Return ONLY the finished email or essay as plain text. "
        "No wrapper labels, no markdown, no explanations.",
    ]
    if permanent_note:
        sections.append(
            "STANDING INSTRUCTION (always follow — applies silently to every generation):\n"
            f"{permanent_note}"
        )
    if profile_block:
        sections.append(profile_block)
    else:
        sections.append(
            "PERSONAL PROFILE: empty — use generic phrasing only. "
            "No placeholder text (no brackets, no [Name], no [Your Name]). "
            "Do not invent names. Do not error."
        )
    if not permanent_note:
        sections.append(
            "PERMANENT NOTE: empty — no standing instruction. Proceed normally."
        )
    if context_block:
        sections.append(context_block)

    if parsed_note["has_tone_instruction"]:
        saved_tone_label = saved_settings["tone_preset"]
        override_label = parsed_note["tone_preset_override"] or saved_tone_label
        sections.append(
            f"{NOTE_TONE_OVERRIDE_RULES}\n"
            f"Saved tone (ignore for this generation): {saved_tone_label}\n"
            f"Apply instead: {override_label}\n"
            f"User tone instruction: {parsed_note['tone_instruction']}"
        )

    if parsed_note["informational_content"]:
        sections.append(
            f"{NOTE_INFORMATIONAL_RULES}\n{parsed_note['informational_content']}"
        )
    elif user_notes and not parsed_note["has_tone_instruction"]:
        sections.append(f"{NOTE_INFORMATIONAL_RULES}\n{user_notes}")

    sections.append(
        "SEED TEXT TO EXPAND (mandatory content — the body MUST fully address this topic):\n"
        f"{text}"
    )
    if length == "short":
        sections.append(GENERATE_SHORT_CONTENT_RULES)
        sections.append(
            "FINAL LENGTH CHECK: Body must be 1 short paragraph or 2–3 sentences only. "
            "No padding. Do not change tone or vocabulary."
        )
    elif length == "medium":
        sections.append(
            "FINAL LENGTH CHECK: Body must be 2–3 paragraphs separated by blank lines. "
            "Email includes greeting, body, and closing. Do not change tone or vocabulary."
        )
    elif length == "long":
        sections.append(
            "FINAL LENGTH CHECK: Body must be 4 or more paragraphs with full detail. "
            "Do not change tone or vocabulary."
        )
    return "\n\n".join(sections)


def _call_llm(
    prompt: str,
    *,
    task: Literal["rewrite", "generate"],
    system: str | None = None,
    num_predict: int | None = None,
    ai_config: dict[str, Any] | None = None,
) -> str:
    effective_system = system or WRITING_AGENT_SYSTEM_PROMPT
    if task == "rewrite":
        temperature = OLLAMA_REWRITE_TEMPERATURE
        effective_predict = num_predict or OLLAMA_REWRITE_NUM_PREDICT
    else:
        temperature = OLLAMA_GENERATE_TEMPERATURE
        effective_predict = num_predict or OLLAMA_GENERATE_NUM_PREDICT

    if ai_config:
        from cloud_ai import CloudAIError, call_cloud_chat  # noqa: PLC0415

        try:
            return call_cloud_chat(
                provider=ai_config["provider"],
                api_key=ai_config["api_key"],
                model=ai_config["model"],
                system=effective_system,
                prompt=prompt,
                temperature=temperature,
                max_tokens=effective_predict,
            )
        except CloudAIError:
            raise

    from server import (  # noqa: PLC0415 — avoid import cycle at module load
        OLLAMA_GRAMMAR_NUM_CTX,
        OllamaError,
        _ollama_generate,
        ensure_ollama_running,
    )

    ensure_ollama_running()
    return _ollama_generate(
        prompt,
        temperature=temperature,
        system=effective_system,
        model=OLLAMA_WRITING_MODEL,
        num_predict=effective_predict,
        num_ctx=OLLAMA_GRAMMAR_NUM_CTX,
    )


def _call_ollama(
    prompt: str,
    *,
    task: Literal["rewrite", "generate"],
    system: str | None = None,
    num_predict: int | None = None,
    ai_config: dict[str, Any] | None = None,
) -> str:
    return _call_llm(
        prompt,
        task=task,
        system=system,
        num_predict=num_predict,
        ai_config=ai_config,
    )


class WritingAgent:
    """Dedicated agent for extension Rewrite and Generate features."""

    model = OLLAMA_WRITING_MODEL

    def rewrite(
        self,
        text: str,
        user_instruction: str,
        context: dict[str, Any] | None = None,
        *,
        direct: bool = False,
        ai_config: dict[str, Any] | None = None,
    ) -> str:
        if not text or not text.strip():
            return ""
        prompt = build_rewrite_prompt(text, user_instruction, context, direct=direct)
        raw = _call_llm(prompt, task="rewrite", ai_config=ai_config)
        cleaned = _clean_output(raw)
        cleaned = apply_rewrite_hard_filters(text, cleaned)
        return _normalize_email_spacing(cleaned)

    def generate(
        self,
        text: str,
        format_type: str,
        notes: str = "",
        context: dict[str, Any] | None = None,
        settings: dict[str, Any] | None = None,
        ai_config: dict[str, Any] | None = None,
    ) -> str:
        if not text or not text.strip():
            return ""
        effective_settings = resolve_effective_generate_settings(settings, notes)
        length = effective_settings["length"]
        complexity = effective_settings["complexity"]
        tone_preset = effective_settings["tone_preset"]
        seed_baseline = build_seed_content_baseline(text, notes)
        system_prompt = _build_generate_system_prompt(
            length, complexity, tone_preset, format_type=format_type
        )
        num_predict = _generate_num_predict_for_length(length)
        prompt = build_generate_prompt(text, format_type, notes, context, settings)
        raw = _call_llm(
            prompt,
            task="generate",
            system=system_prompt,
            num_predict=num_predict,
            ai_config=ai_config,
        )
        cleaned = _clean_output(raw)
        cleaned = _take_first_complete_draft(cleaned)
        retry_instruction = _build_length_retry_instruction(length, format_type)
        for _attempt in range(2):
            if not retry_instruction or _meets_generate_length_requirement(
                cleaned, format_type, length
            ):
                break
            retry_prompt = f"{prompt}\n\n{retry_instruction}"
            raw = _call_llm(
                retry_prompt,
                task="generate",
                system=system_prompt,
                num_predict=num_predict,
                ai_config=ai_config,
            )
            cleaned = _take_first_complete_draft(_clean_output(raw))
        cleaned = apply_generate_hard_filters(
            cleaned,
            format_type=format_type,
            settings=effective_settings,
            seed_baseline=seed_baseline,
        )
        cleaned = _enforce_length_structure(cleaned, format_type, length)
        return _normalize_email_spacing(cleaned)


_agent = WritingAgent()


def rewrite_text(
    text: str,
    user_instruction: str = "neutral",
    context: dict[str, Any] | None = None,
    *,
    direct: bool = False,
    ai_config: dict[str, Any] | None = None,
) -> str:
    return _agent.rewrite(text, user_instruction, context, direct=direct, ai_config=ai_config)


def generate_text(
    text: str,
    format_type: str,
    notes: str = "",
    context: dict[str, Any] | None = None,
    settings: dict[str, Any] | None = None,
    ai_config: dict[str, Any] | None = None,
) -> str:
    return _agent.generate(
        text, format_type, notes, context, settings, ai_config=ai_config
    )
