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
OLLAMA_REWRITE_TEMPERATURE = float(os.environ.get("OLLAMA_REWRITE_TEMPERATURE", "0.45"))
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
    "1. REWRITE — change tone/style of selected text by editing word choice and sentence "
    "structure only. Keep the same information, structure, and roughly the same length.\n"
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
THREE INDEPENDENT SETTINGS — apply all three at the same time; each does its own job only:
  • LENGTH controls structure and nothing else. It does not change tone or vocabulary.
  • TONE controls how it sounds and nothing else. It does not change paragraph count or word choice.
  • COMPLEXITY controls vocabulary and nothing else. It does not change structure or tone.
Changing one setting must never affect the other two."""

GENERATE_STRICT_RULES = """\
OUTPUT RULES (non-negotiable):
  • Hit the LENGTH structure exactly, regardless of tone or complexity.
  • Apply TONE to greeting, subject, body phrasing, and sign-off consistently.
  • Apply COMPLEXITY only to word choice within the required structure and tone.
  • Never invent recipient names (John, Jane, Sarah, Alice, Bob, etc.).
    Use [Name] in greetings unless the user profile supplies a recipient name.
  • Use the saved profile full name on the sign-off line when available.
    If no profile name is saved, use [Your Name] — never invent a sender name.
  • Never leave bracketed instructions or template text in the output except [Name] and [Your Name].
  • Apply saved user profile (name, sign-off preference, job title, etc.) automatically."""

GENERATE_LENGTH_GUIDANCE: dict[str, str] = {
    "short": """\
LENGTH — structure only (independent of tone and complexity; hit this exactly):
  • Email BODY (between greeting and sign-off): exactly 1 paragraph, exactly 2 sentences.
    No extra body lines or padding. The first body sentence IS the point — no warm-up,
    no opener, no filler before the reason for the email.
  • CONTENT RULE: include ONLY what the seed input says — nothing else. Never add extra
    instructions, requests, or topics the user did not mention (no "please review changes",
    "provide feedback", "let me know if you have questions" unless those were in the input).
  • Example: seed "let the team know the deadline changed" → body only says the deadline changed.
  • Essay: exactly 1 paragraph, exactly 2 sentences total. Start with the point immediately.
  • Greeting, subject line, and sign-off are outside the body and do not count toward these limits.
  • REQUIRED COUNT: 1 body paragraph, 2 body sentences — verify before finishing.""",
    "medium": """\
LENGTH — structure only (independent of tone and complexity; hit this exactly):
  • Email BODY (between greeting and sign-off): exactly 3 paragraphs, each paragraph
    exactly 3 sentences (9 body sentences total). Separate paragraphs with one blank line.
  • Essay: exactly 3 paragraphs, each paragraph exactly 3 sentences.
  • Do NOT stop at 1 short paragraph — medium requires multiple paragraphs with detail.
  • REQUIRED COUNT: 3 body paragraphs, 3 sentences each — verify before finishing.""",
    "long": """\
LENGTH — structure only (independent of tone and complexity; hit this exactly):
  • Email BODY (between greeting and sign-off): exactly 4 paragraphs minimum,
    each paragraph 3–4 sentences. Include full detail, context, and supporting points
    spread across all paragraphs.
  • Essay: 4 or more paragraphs, each with 3–4 sentences and supporting detail.
  • Do NOT stop at 1 short paragraph — long requires substantial multi-paragraph content.
  • REQUIRED COUNT: at least 4 body paragraphs, 3–4 sentences each — verify before finishing.""",
}

GENERATE_COMPLEXITY_GUIDANCE: dict[str, str] = {
    "simple": """\
COMPLEXITY — vocabulary only (independent of length and tone; word choice only):
  • Use short everyday words — no word longer than 2 syllables where a shorter word works.
  • Keep sentences short and direct (about 15 words or fewer when possible).
  • Sound like a real person talking — not a formal document or status report.
  • REWRITE stiff phrasing into plain speech. Example:
    "extended until next Friday due to additional client requests for revisions"
    → "pushed to next Friday because the client asked for more changes."
  • AVOID: utilize, commence, facilitate, pursuant, regarding, inquire, request (as formal noun),
    prior to, subsequent, additionally, appreciate, would appreciate, kindly, herein,
    extended until, due to additional, client requests for revisions, "I am writing to request",
    "I would like to inquire", "I hope this finds you well", "Please be advised that",
    "I am reaching out to", corporate or academic phrasing.
  • USE: get, ask, need, want, help, send, make, use, check, tell, push, moved, changed,
    "I wanted to ask", "can I get", "because", "so", plain everyday language and contractions.
  • Do not add or remove paragraphs or sentences — LENGTH controls structure.
  • Do not change greeting style or formality — TONE controls how it sounds.""",
    "standard": """\
COMPLEXITY — vocabulary only (independent of length and tone; word choice only):
  • Use normal professional business vocabulary — clear, balanced, and readable.
  • AVOID: commence, pursuant, herein, thereof, ergo, overly academic jargon, slang.
  • USE: standard professional words (provide, update, review, discuss, confirm, follow up,
    appreciate, request, submit) in clear professional sentences.
  • Do not add or remove paragraphs or sentences — LENGTH controls structure.
  • Do not change greeting style or formality — TONE controls how it sounds.""",
    "advanced": """\
COMPLEXITY — vocabulary only (independent of length and tone; word choice only):
  • Use sophisticated vocabulary and varied sentence structure throughout every paragraph.
  • USE: expedite, facilitate, comprehensive, subsequently, articulate, leverage, paramount,
    accordingly, endeavor, pursuant, prior to, notwithstanding, subordinate clauses,
    and formal phrasing in every sentence.
  • AVOID: casual contractions, slang, choppy one-clause-only sentences, simple grade-school words
    where a precise professional term fits.
  • Do not add or remove paragraphs or sentences — LENGTH controls structure.
  • Do not change greeting style or formality — TONE controls how it sounds.""",
}

TONE_PRESET_GUIDANCE: dict[str, str] = {
    "formal": """\
TONE — how it sounds only (independent of length and complexity):
  • Opening: "Dear [Name]"
  • Body sentences: professional and respectful
  • Sign-off: "Sincerely" then the user's name from profile when saved
  • Subject line must sound formal""",
    "friendly": """\
TONE — how it sounds only (independent of length and complexity):
  • Opening: "Hi [Name]"
  • Body sentences: warm and human but get to the point fast
  • On medium or long length only: optional one-line opener like "Hope you're having a good one"
  • On short length: skip any body opener — first body sentence is the point
  • NEVER use "I hope you're doing well" or any variation — completely banned
  • Sign-off: "Best" then the user's name from profile when saved
  • Subject line must sound warm but clear""",
    "casual": """\
TONE — how it sounds only (independent of length and complexity):
  • Opening: "Hey [Name]" or just their name
  • Body sentences: direct and conversational — get to the point fast
  • No body warm-up or filler lines at any length
  • NEVER use "I hope you're doing well" or any variation — completely banned
  • Sign-off: "Thanks" then the user's name from profile when saved (if natural)
  • Subject line must sound informal""",
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
BANNED FILLER:
  • Friendly and casual tones: NEVER "I hope you're doing well", "I hope this finds you well",
    or any variation — at any length. No polite warm-up lines on short length.
  • Formal tone only: at most ONE short polite opener line in the body on medium/long length;
    on short length the body starts with the point — no opener.
  • All tones: "Looking forward to hearing from you", "Thank you for your time and consideration",
    "Please do not hesitate to contact me" — never use."""

GENERATE_SHORT_CONTENT_RULES = """\
SHORT LENGTH CONTENT (mandatory when length is short):
  • Include ONLY information from the seed input and any informational user note.
  • Never add sentences, instructions, or topics the user did not mention.
  • Do NOT add "please review changes", "provide feedback", "let me know if you have questions",
    or similar unless the user specifically said those in the input."""

GENERATE_FRIENDLY_SIMPLE_VOICE = """\
FRIENDLY/CASUAL + SIMPLE (when tone is friendly or casual and complexity is simple):
  • Write like a real person talking to a colleague — warm but plain.
  • Prefer "pushed to", "moved to", "because", "asked for" over formal noun-heavy phrasing.
  • Use contractions where natural (we're, it's, that's). Never sound like a legal memo."""

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
  • If the user says "make it casual", use contractions and simpler everyday words.
  • If the user says "make it concise", shorten wording but keep every fact.
  • Preserve line breaks, greetings, and sign-offs that already exist in the selection.
  • Nothing gets added; nothing removed except what is necessary to change the tone.
  • Output must read like the same message in a different voice — not a different message."""

TONE_REWRITE_EXAMPLES: dict[str, str] = {
    "formal": """\
EXAMPLE (formal):
  Before: "Hey, can you send me that file when you get a sec?"
  After: "Could you please send the file at your earliest convenience?"
  (Same request, more professional wording — no new sentences.)""",
    "friendly": """\
EXAMPLE (friendly):
  Before: "Please submit the form by Friday."
  After: "If you can, please send the form in by Friday — appreciate it."
  (Warmer wording inside the same sentence — no greeting or thanks added.)""",
    "casual": """\
EXAMPLE (casual):
  Before: "Please be advised that the office will be closed on Monday."
  After: "Heads up — the office is closed on Monday."
  (Simpler, conversational words — same fact, no filler.)""",
    "concise": """\
EXAMPLE (concise):
  Before: "I am writing to inform you that the meeting has been rescheduled to 3pm."
  After: "The meeting is rescheduled to 3pm."
  (Shorter, same fact — may remove padding words only.)""",
    "simple": """\
EXAMPLE (simple):
  Before: "We must expedite the procurement process to mitigate further delays."
  After: "We need to speed up buying so we don't fall further behind."
  (Plain words a non-expert would use — same meaning.)""",
}

TONE_REWRITE_PRESET_INSTRUCTIONS: dict[str, str] = {
    "formal": "Rewrite in a professional, formal tone.",
    "friendly": "Rewrite in a warm and friendly tone.",
    "casual": "Rewrite in a casual, natural tone.",
    "concise": "Rewrite to be more concise.",
    "simple": "Rewrite using simpler, easier-to-understand words.",
}

TONE_REWRITE_OUTPUT_RULE = " Return only the rewritten text, nothing else."


def _is_concise_rewrite_instruction(instruction: str) -> bool:
    lower = (instruction or "").lower()
    return any(
        token in lower
        for token in ("concise", "shorter", "shorten", "brief", "trim", "condense")
    )


def _detect_rewrite_tone_preset(instruction: str) -> str | None:
    lower = (instruction or "").lower()
    if any(token in lower for token in ("formal", "professional", "businesslike")):
        return "formal"
    if "casual" in lower or "relaxed" in lower or "informal" in lower:
        return "casual"
    if "friendly" in lower or "warm" in lower:
        return "friendly"
    if _is_concise_rewrite_instruction(instruction):
        return "concise"
    if any(token in lower for token in ("simple", "simpler", "plain", "easier")):
        return "simple"
    return None


def _rewrite_tone_examples_block(instruction: str) -> str:
    preset = _detect_rewrite_tone_preset(instruction)
    if preset and preset in TONE_REWRITE_EXAMPLES:
        return TONE_REWRITE_EXAMPLES[preset]
    return ""


def _original_has_closing_block(original: str) -> bool:
    lines = [line.strip() for line in original.replace("\r\n", "\n").split("\n") if line.strip()]
    if not lines:
        return False
    return any(
        _rewrite_line_is_signoff(line) or _rewrite_line_is_thanks_closing(line)
        for line in lines[-2:]
    )


def _closing_sentence_protected(sentence: str, original: str) -> bool:
    if not _original_has_closing_block(original):
        return False
    stripped = sentence.strip()
    if _rewrite_line_is_signoff(stripped) or _rewrite_line_is_thanks_closing(stripped):
        return True
    orig_lines = [line.strip() for line in original.replace("\r\n", "\n").split("\n") if line.strip()]
    if orig_lines and stripped.lower() == orig_lines[-1].lower():
        return True
    return False


def _extract_closing_lines(original: str) -> list[str]:
    lines = original.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    last_signoff_idx = -1
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if _rewrite_line_is_signoff(stripped) or _rewrite_line_is_thanks_closing(stripped):
            last_signoff_idx = index

    if last_signoff_idx < 0:
        return []

    end_idx = last_signoff_idx
    while end_idx + 1 < len(lines):
        nxt = lines[end_idx + 1].strip()
        if not nxt:
            end_idx += 1
            continue
        if len(nxt.split()) <= 3:
            end_idx += 1
            continue
        break

    return lines[last_signoff_idx : end_idx + 1]


def _rewritten_has_closing_block(rewritten: str, original: str) -> bool:
    if not _original_has_closing_block(original):
        return True
    closing = _extract_closing_lines(original)
    if not closing:
        return False
    rewritten_lower = rewritten.lower()
    return any(part.strip().lower() in rewritten_lower for part in closing if part.strip())


def _restore_missing_closing_lines(original: str, rewritten: str) -> str:
    closing = _extract_closing_lines(original)
    if not closing or _rewritten_has_closing_block(rewritten, original):
        return rewritten

    result = rewritten.rstrip()
    if result:
        result += "\n\n"
    result += "\n".join(closing)
    return result.strip()


def _rewrite_length_bounds(instruction: str) -> tuple[float, float]:
    if _is_concise_rewrite_instruction(instruction):
        return 0.40, 1.0
    return 0.85, 1.15


def check_rewrite_quality(
    original: str,
    rewritten: str,
    instruction: str = "",
) -> dict[str, Any]:
    issues: list[str] = []
    source = (original or "").strip()
    result = (rewritten or "").strip()
    if not result:
        issues.append("empty")

    orig_words = len(source.split())
    out_words = len(result.split())
    min_ratio, max_ratio = _rewrite_length_bounds(instruction)
    ratio = out_words / max(orig_words, 1)
    if orig_words and (ratio < min_ratio or ratio > max_ratio):
        issues.append("length_ratio")

    for pattern in _REWRITE_FILLER_PATTERNS:
        if pattern.search(result) and not pattern.search(source):
            issues.append("filler_leak")
            break

    if _original_has_closing_block(source) and not _rewritten_has_closing_block(result, source):
        issues.append("missing_closing")

    preset = _detect_rewrite_tone_preset(instruction)
    if preset == "casual":
        has_contraction = bool(re.search(r"\b\w+'\w+\b", result))
        simple_markers = ("just", "hey", "yeah", "gonna", "kinda", "pretty")
        if orig_words >= 8 and not has_contraction and not any(m in result.lower() for m in simple_markers):
            orig_avg = sum(len(word) for word in source.split()) / max(orig_words, 1)
            out_avg = sum(len(word) for word in result.split()) / max(out_words, 1)
            if out_avg >= orig_avg:
                issues.append("weak_casual_tone")

    return {"ok": not issues, "issues": issues, "length_ratio": ratio}


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
    re.compile(r"\breach out\b", re.IGNORECASE),
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
            updated = re.sub(
                r"^(?:Dear|Hi|Hey|Hello)\s+[^,\n]+,\s*",
                "",
                stripped,
                flags=re.IGNORECASE,
            )
            if updated == stripped:
                updated = re.sub(
                    r"^(?:Dear|Hi|Hey|Hello)\b[!,.\s]*",
                    "",
                    stripped,
                    count=1,
                    flags=re.IGNORECASE,
                ).lstrip()
            if updated and updated != stripped:
                lines[0] = updated
            elif _rewrite_line_is_standalone_greeting(stripped):
                lines.pop(0)
            else:
                break
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


def _strip_excess_rewrite_sentences(
    original: str,
    rewritten: str,
    *,
    instruction: str = "",
) -> str:
    original_count = _rewrite_content_line_count(original)
    if original_count == 0:
        return rewritten

    max_allowed = original_count + (0 if _is_concise_rewrite_instruction(instruction) else 1)
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
            not _closing_sentence_protected(all_sentences[-1], original)
            and (
                _rewrite_line_is_thanks_closing(all_sentences[-1])
                or _rewrite_sentence_is_added(all_sentences[-1], original)
            )
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


def apply_rewrite_hard_filters(
    original: str,
    rewritten: str,
    *,
    instruction: str = "",
) -> str:
    if not rewritten or not original:
        return rewritten

    source = original.strip()
    result = rewritten.strip()
    result = _remove_added_greeting_signoff_lines(source, result)
    result = _remove_added_content_lines(source, result)
    result = _remove_added_filler_sentences(source, result)
    result = _strip_added_thanks_closing(source, result)
    result = _strip_excess_rewrite_sentences(source, result, instruction=instruction)
    result = _fix_rewrite_exclamation_marks(source, result)
    result = _fix_rewrite_leading_artifacts(result)
    result = _restore_missing_closing_lines(source, result)
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


def _meets_generate_length_requirement(text: str, format_type: str, length: str) -> bool:
    if format_type != "email" or length == "short":
        return True
    paragraph_count = _count_email_body_paragraphs(text)
    if length == "medium":
        return paragraph_count >= 2
    if length == "long":
        return paragraph_count >= 4
    return True


def _build_length_retry_instruction(length: str, format_type: str) -> str:
    if format_type != "email" or length == "short":
        return ""
    if length == "medium":
        return (
            "LENGTH RETRY — your previous draft body had too few paragraphs. "
            "Output ONE email only with exactly 3 body paragraphs, each with exactly 3 sentences, "
            "separated by blank lines. Do not repeat or stack multiple drafts."
        )
    return (
        "LENGTH RETRY — your previous draft body had too few paragraphs. "
        "Output ONE email only with at least 4 body paragraphs, each with 3–4 sentences, "
        "separated by blank lines. Do not repeat or stack multiple drafts."
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
        allow_good_one = tone_preset == "friendly" and length in {"medium", "long"}
        filtered = _strip_friendly_casual_hope_phrases(filtered, allow_good_one=allow_good_one)

    if format_type == "email":
        sections = _parse_email_sections(filtered)
        sections["body"] = _filter_email_body(
            sections["body"],
            tone_preset=tone_preset,
            length=length,
        )
        filtered = _reassemble_email_sections(sections)
    else:
        filtered = _filter_prose_block(filtered, tone_preset=tone_preset, length=length)

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


def _normalize_generate_names(text: str, profile: dict[str, Any]) -> str:
    if not text or not text.strip():
        return text

    saved_name = _extract_profile_full_name(profile)
    signoff_name = saved_name or "[Your Name]"
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
            if name_part in ("[Name]", "[Your Name]"):
                normalized_lines.append(line)
                continue
            if saved_name and name_part.lower() == saved_name.lower():
                normalized_lines.append(line)
                continue
            if name_part.lower().startswith("professor"):
                normalized_lines.append(f"{prefix} Professor [Name]")
            else:
                normalized_lines.append(f"{prefix} [Name]")
            continue

        signoff_match = _SIGNOFF_INLINE_NAME_RE.match(stripped)
        if signoff_match:
            prefix = signoff_match.group(1)
            name_part = signoff_match.group(2).strip()
            if name_part in ("[Name]", "[Your Name]"):
                normalized_lines.append(line)
                continue
            if saved_name and name_part.lower() == saved_name.lower():
                normalized_lines.append(line)
                continue
            normalized_lines.append(f"{prefix} {signoff_name}")
            continue

        normalized_lines.append(line)

    result = "\n".join(normalized_lines)
    result_lines = result.split("\n")
    for index in range(len(result_lines) - 1):
        current = result_lines[index].strip()
        nxt = result_lines[index + 1].strip()
        if not _is_signoff_line(current) or not nxt:
            continue
        if nxt in ("[Name]", "[Your Name]"):
            continue
        if saved_name and nxt.lower() == saved_name.lower():
            continue
        if re.fullmatch(r"[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?", nxt):
            result_lines[index + 1] = signoff_name

    return "\n".join(result_lines)


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
    preset = _detect_rewrite_tone_preset(text)
    if preset and preset in TONE_REWRITE_PRESET_INSTRUCTIONS:
        if not text or text.lower() in {preset, f"{preset} tone", f"make it {preset}"}:
            text = TONE_REWRITE_PRESET_INSTRUCTIONS[preset]
    if not text:
        text = "Rewrite to sound clear and natural."
    lower = text.lower()
    if "return only" not in lower and "nothing else" not in lower:
        if not text.endswith((".", "!", "?")):
            text += "."
        text += TONE_REWRITE_OUTPUT_RULE
    return text.strip()


def _build_rewrite_sections(
    text: str,
    instruction: str,
    context: dict[str, Any] | None,
) -> list[str]:
    tone_instruction = _normalize_tone_instruction(instruction)
    sections: list[str] = [TONE_REWRITE_STRICT_RULES]
    examples = _rewrite_tone_examples_block(instruction)
    if examples:
        sections.append(examples)
    context_block = format_document_context(context)
    if context_block:
        sections.append(context_block)
    sections.append(
        f"USER INSTRUCTION:\n{tone_instruction}\n\nSELECTED TEXT TO REWRITE:\n{text}"
    )
    return sections


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
        return "\n\n".join(_build_rewrite_sections(text, instruction, context))

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
    examples = _rewrite_tone_examples_block(instruction)
    if examples:
        sections.append(examples)
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
    labels = {
        "fullName": "Full name",
        "full_name": "Full name",
        "signOff": "Preferred sign-off",
        "sign_off": "Preferred sign-off",
        "jobTitle": "Job title",
        "job_title": "Job title",
        "companyName": "Company name",
        "company_name": "Company name",
        "schoolName": "School name",
        "school_name": "School name",
        "email": "Email address",
        "phone": "Phone number",
    }
    lines: list[str] = []
    for key, label in labels.items():
        value = str(profile.get(key) or "").strip()
        if value:
            lines.append(f"- {label}: {value}")
    if not lines:
        return ""
    extra = (
        "\n- If a preferred sign-off is saved, use that exact line instead of the default "
        "tone sign-off when they differ."
        "\n- Always use the saved full name on the sign-off line when available — "
        "never output [Your Name] or similar placeholders."
    )
    return (
        "USER PROFILE (use automatically — especially in sign-offs and contact details):\n"
        + "\n".join(lines)
        + extra
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


def _build_complexity_rules(complexity: str, tone_preset: str = "friendly") -> str:
    rules = GENERATE_COMPLEXITY_GUIDANCE.get(
        complexity, GENERATE_COMPLEXITY_GUIDANCE["standard"]
    )
    if complexity == "simple" and tone_preset in {"friendly", "casual"}:
        rules = f"{rules}\n\n{GENERATE_FRIENDLY_SIMPLE_VOICE}"
    return rules


def _build_generate_system_prompt(length: str, complexity: str, tone_preset: str = "friendly") -> str:
    parts = [
        WRITING_AGENT_SYSTEM_PROMPT,
        "ACTIVE LENGTH SETTING — enforce this exact structure in every generate response:",
        _build_length_rules(length),
        "ACTIVE COMPLEXITY SETTING — enforce this exact vocabulary in every generate response:",
        _build_complexity_rules(complexity, tone_preset),
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
    return "\n\n".join(
        [
            GENERATE_INDEPENDENCE_RULES,
            GENERATE_STRICT_RULES,
            _build_length_rules(length),
            _build_tone_rules(tone_preset, format_type),
            _build_complexity_rules(complexity, tone_preset),
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
    elif length == "medium":
        sections.append(
            "FINAL LENGTH CHECK: The email body MUST be exactly 3 paragraphs with 3 sentences "
            "each, separated by blank lines. Count before you finish."
        )
    elif length == "long":
        sections.append(
            "FINAL LENGTH CHECK: The email body MUST be at least 4 paragraphs with 3–4 sentences "
            "each, separated by blank lines. Count before you finish."
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
        cleaned = apply_rewrite_hard_filters(
            text,
            cleaned,
            instruction=user_instruction,
        )
        quality = check_rewrite_quality(text, cleaned, user_instruction)
        if not quality["ok"] and "missing_closing" in quality["issues"]:
            retry_prompt = (
                f"{prompt}\n\nIMPORTANT: Keep every greeting and sign-off line from the "
                "original selection. Do not remove closing lines such as Thanks or a name."
            )
            raw = _call_llm(retry_prompt, task="rewrite", ai_config=ai_config)
            cleaned = apply_rewrite_hard_filters(
                text,
                _clean_output(raw),
                instruction=user_instruction,
            )
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
        system_prompt = _build_generate_system_prompt(length, complexity, tone_preset)
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
        if length in {"medium", "long"}:
            retry_instruction = _build_length_retry_instruction(length, format_type)
            if retry_instruction and not _meets_generate_length_requirement(
                cleaned, format_type, length
            ):
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
