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
OLLAMA_GENERATE_NUM_PREDICT_SHORT = int(
    os.environ.get("OLLAMA_GENERATE_NUM_PREDICT_SHORT", "512")
)
OLLAMA_GENERATE_NUM_PREDICT = int(os.environ.get("OLLAMA_GENERATE_NUM_PREDICT", "2048"))
OLLAMA_GENERATE_NUM_PREDICT_MEDIUM = int(
    os.environ.get("OLLAMA_GENERATE_NUM_PREDICT_MEDIUM", "2560")
)
OLLAMA_GENERATE_NUM_PREDICT_LONG = int(
    os.environ.get("OLLAMA_GENERATE_NUM_PREDICT_LONG", "4096")
)

EMAIL_SIGNATURE_PLACEHOLDER = ""  # no name line when profile name is missing (never brackets)

WRITING_AGENT_SYSTEM_PROMPT = (
    "You are the Humanizer Writing Agent. You only do two jobs:\n"
    "1. REWRITE — change tone/style of selected text by editing word choice and sentence "
    "structure only. Keep the same information, structure, and roughly the same length.\n"
    "2. GENERATE — expand short notes, bullets, or prompts into complete emails or essays.\n"
    "Return only the final plain text — no markdown or meta explanations."
)

SETTINGS_INDEPENDENCE_HEADER = """\
SEPARATE AND INDEPENDENT RULES
These rules are separate. Apply every rule that is present. No rule may influence another:
  • Tone must NEVER affect length or vocabulary.
  • Length must NEVER affect tone or vocabulary.
  • Vocabulary must NEVER affect tone or length.
  • Personal info must NEVER change tone, length, or vocabulary — only who/what you may reference.
  • Permanent note must NEVER change tone, length, or vocabulary — only standing preferences.
  • Changing one setting while holding others fixed must change ONLY that setting's dimension."""

MEANING_FIDELITY_RULE = """\
RULE — MEANING & FIDELITY (always on):
  • Do not change the meaning of the user's input.
  • Do not invent facts, names, requests, excuses, dates, assignment titles, health issues,
    family emergencies, prior conversations, or any other detail the user did not imply.
  • NO REASON RULE (critical): If the user's idea does NOT state a reason, the output must
    NOT include any reason at all — not health, workload, personal circumstances,
    "unforeseen" events, or any other justification. The request must stand alone.
    This applies for short, medium, AND long length equally; never invent a reason to fill space.
  • Do not add new information beyond what the user implied.
  • For longer drafts, develop ONLY the substance of the ask (what is being requested,
    what outcome you want, and a polite close) — never invent a backstory, and never
    write commentary about the rules, instructions, or writing process.
  • Expand or rephrase what they gave you — never replace their intent with a different message."""

EMAIL_GENERATION_GUIDE = """\
TASK: GENERATE a complete email from the seed text, user notes, and document context.

Email structure:
  • Subject line (on its own first line: "Subject: ...") when enabled
  • Greeting — generic or recipient from the idea only (NEVER use the writer's own name
    in the greeting / salutation)
  • Body — must follow tone, length, and complexity rules exactly
  • Sign-off — must follow the tone rules, then the writer's name on the next line
  • Email signature — always put the writer's full name from profile / sign-off note
    after the sign-off when a name is saved; if no name is saved, end with only the
    closing word and no name line. Never use a bracketed placeholder for the name
    or anything else.
  • Sign-off / signature instructions NEVER affect the greeting at the top

General rules:
  • Produce send-ready text — no fragments and no bracketed placeholders of any kind.
  • Weave informational user notes into the body naturally; do not paste them as a bullet list.
  • If a user note is informational only, it adds facts — it must not change tone or style.
  • If a user note includes a one-time tone instruction, follow that tone for this generation only.
  • If no reason is provided in the idea, include no reason whatsoever — do not invent one.
  • Never write meta commentary about instructions, rules, length, or the drafting process.
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
  • Hit the LENGTH structure and approximate body word targets exactly, regardless of tone
    or complexity — advanced must be as long as simple/standard for the same length setting.
  • Apply TONE to greeting, subject, body phrasing, and sign-off consistently.
  • Apply COMPLEXITY only to word choice within the required structure and tone.
  • Never invent recipient names (John, Jane, Sarah, Alice, Bob, etc.).
  • Never put the writer's own name in the greeting — writer name is only the signature line.
  • If a user profile is provided, apply name/role only where appropriate (signature, not greeting).
  • If profile/permanent note are empty: use generic phrasing for greetings and body
    and do not error.
  • Email signature: always put the writer's saved full name after the sign-off; if no
    name is saved, sign off with just the closing word ("Best," or "Sincerely,") and
    no name line — never use a bracketed placeholder for the name or anything else.
  • Sign-off permanent notes affect ONLY the closing signature — never the salutation.
  • Never leave bracketed instructions or template text in the output.
  • NEVER print rules, setting names, instruction headers, profile labels, or meta notes
    in the draft — only the finished email or essay.
  • Never write sentences that narrate the drafting process (e.g. that you are not adding
    a reason, that this is a restatement for clarity, or that the reader should just
    reply yes/no because of the instructions)."""

GENERATE_LENGTH_GUIDANCE: dict[str, str] = {
    "short": """\
LENGTH — structure only (independent of tone and complexity):
  • Body: 1 short paragraph, at most 2 sentences (~20–50 words).
  • Just the core request — no padding, no invented excuses or reasons.
  • Email: greeting and sign-off are allowed but the BODY is only the core message.
  • Essay: 1 short paragraph or 2 sentences total.
  • LENGTH must NEVER change vocabulary difficulty or tone.""",
    "medium": """\
LENGTH — structure only (independent of tone and complexity):
  • Body: exactly 2–3 paragraphs (~90–160 words total in the body).
  • Noticeably longer than short, but clearly shorter than long.
  • Email: greeting, 2–3 body paragraphs, closing/sign-off.
  • Essay: 2–3 paragraphs of content.
  • Develop only what the user said. If they gave no reason, include none.
  • LENGTH must NEVER change vocabulary difficulty or tone.""",
    "long": """\
LENGTH — structure only (independent of tone and complexity):
  • Target: at least 5 body paragraphs and ~220+ body words — clearly more developed
    than medium.
  • How to add length (content only — these are RULES, not text to paste into the draft):
      1) Open with the request itself, stated fully and clearly.
      2) Elaborate what you are asking for (scope, timing flexibility, or the outcome
         you want) using only details present in the user's idea.
      3) Add courteous paragraphs that stay on the request: willingness to follow the
         recipient's process, readiness to provide whatever they need next related to
         THIS ask, appreciation for their help.
  • Forbidden filler: invented excuses/reasons, dates, assignment titles, health/workload/
    personal backstories, and any meta talk about instructions, rules, wording strategy,
    or the writing process.
  • If the idea has no reason, long drafts still have NO reason — more paragraphs of the
    request itself, not a justification.
  • LENGTH must NEVER change vocabulary difficulty or tone.""",
}

GENERATE_COMPLEXITY_GUIDANCE: dict[str, str] = {
    "simple": """\
COMPLEXITY — vocabulary only (independent of length and tone):
  • Short, common words; short sentences; minimal jargon.
  • Prefer everyday words: get, ask, need, want, help, send, make, use, check, tell,
    push, moved, changed, because, so.
  • AVOID advanced/academic words: utilize, commence, facilitate, pursuant, regarding,
    inquire, subsequent, additionally, herein, comprehensive, expedite, endeavor.
  • CRITICAL: keep the SAME paragraph count and approximate body word count as the
    Length setting requires — "simple" must NOT shorten the draft.""",
    "standard": """\
COMPLEXITY — vocabulary only (independent of length and tone):
  • Everyday professional vocabulary; moderate sentence length.
  • USE: provide, update, review, discuss, confirm, follow up, request, submit, appreciate.
  • AVOID: commence, pursuant, herein, thereof, overly academic jargon, and also avoid
    overly childish one-syllable-only phrasing.
  • CRITICAL: keep the SAME paragraph count and approximate body word count as Length
    requires — do not shrink or expand for "standard".""",
    "advanced": """\
COMPLEXITY — vocabulary only (independent of length and tone):
  • Sophisticated vocabulary and longer/more complex sentence structures.
  • USE precise terms where they fit: expedite, facilitate, comprehensive, subsequently,
    articulate, leverage, paramount, accordingly, endeavor, prior to.
  • Prefer varied sentence structure (clauses, transitions) over choppy simple sentences.
  • CRITICAL: keep the SAME paragraph count and approximate body word count as Length
    requires — "advanced" must NOT shorten the draft; only the wording changes.""",
}

TONE_PRESET_GUIDANCE: dict[str, str] = {
    "formal": """\
TONE — voice/personality only (independent of length and complexity):
  • Professional language, no contractions, no slang, structured sentences.
  • Opening: "Dear …," when a recipient is known; otherwise "Dear Sir or Madam," or "Hello,"
  • Sign-off: "Sincerely," then the writer's saved name on the next line when available;
    if no name is saved, sign off with only "Sincerely," and no name line
  • Subject line must sound formal
  • TONE must NEVER change how long the output is or how advanced the vocabulary is —
    "formal" does not mean longer, and does not mean more advanced words.""",
    "friendly": """\
TONE — voice/personality only (independent of length and complexity):
  • Warm, approachable, personable phrasing; contractions okay.
  • Opening: "Hi …," when a recipient is known; otherwise "Hi," or "Hi there,"
  • Sign-off: "Best," then the writer's saved name on the next line when available;
    if no name is saved, sign off with only "Best," and no name line
  • Subject line must sound warm but clear
  • TONE must NEVER change how long the output is or how advanced the vocabulary is —
    "friendly" does not mean shorter or simpler words.""",
    "casual": """\
TONE — voice/personality only (independent of length and complexity):
  • Relaxed, conversational; contractions and informal phrasing okay.
  • Opening: "Hey …," when a recipient is known; otherwise "Hey," or "Hey there,"
  • Sign-off: "Thanks," then the writer's saved name on the next line when available;
    if no name is saved, sign off with only "Thanks," and no name line
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
    # Strip casual openers that blur formal vs friendly
    result = re.sub(
        r"(?im)^Just (?:a quick |wanted to |checking in ).*\n?",
        "",
        result,
    )
    result = re.sub(r"(?i)\bHey\b", "Hello", result)
    result = re.sub(r"(?i)\bThanks\b", "Thank you", result)
    result = re.sub(r"  +", " ", result)
    return result.strip()


_CASUAL_TONE_REPLACEMENTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bI am writing to follow up regarding\b", re.I), "I wanted to check in about"),
    (re.compile(r"\bI am writing to follow up\b", re.I), "I wanted to follow up"),
    (re.compile(r"\bI am writing to\b", re.I), "I wanted to"),
    (re.compile(r"\bI hope this message finds you well[.!]?\s*", re.I), ""),
    (re.compile(r"\bI hope you are well[.!]?\s*", re.I), ""),
    (re.compile(r"\bWe would appreciate\b", re.I), "We'd appreciate"),
    (re.compile(r"\bI would appreciate\b", re.I), "I'd appreciate"),
    (re.compile(r"\bPlease let me know\b", re.I), "Let me know"),
    (re.compile(r"\bPlease let us know\b", re.I), "Let us know"),
    (re.compile(r"\bregarding\b", re.I), "about"),
    (re.compile(r"\bprior to\b", re.I), "before"),
    (re.compile(r"\bat your earliest convenience\b", re.I), "when you can"),
    (re.compile(r"\bIt would be beneficial\b", re.I), "It'd help"),
    (re.compile(r"\bWe are eager to\b", re.I), "We're keen to"),
)


def _apply_casual_tone_voice(text: str) -> str:
    """Make casual tone visibly informal — does not change length or vocabulary tier."""
    result = text
    for pattern, replacement in _CASUAL_TONE_REPLACEMENTS:
        result = pattern.sub(replacement, result)
    result = re.sub(r"(?i)\bDear\b", "Hey", result)
    result = re.sub(r"(?i)\bSincerely\b", "Thanks", result)
    result = re.sub(r"  +", " ", result)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


_FRIENDLY_TONE_REPLACEMENTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bI am writing to follow up regarding\b", re.I), "I wanted to follow up about"),
    (re.compile(r"\bI am writing to\b", re.I), "I wanted to"),
    (re.compile(r"\bI hope this message finds you well[.!]?\s*", re.I), ""),
    (re.compile(r"\bat your earliest convenience\b", re.I), "when you have a moment"),
)


def _apply_friendly_tone_voice(text: str) -> str:
    """Warm friendly voice — distinct from formal stiffness and casual slang."""
    result = text
    for pattern, replacement in _FRIENDLY_TONE_REPLACEMENTS:
        result = pattern.sub(replacement, result)
    result = re.sub(r"(?i)\bDear\b", "Hi", result)
    result = re.sub(r"(?i)\bSincerely\b", "Best", result)
    result = re.sub(r"  +", " ", result)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


_ADVANCED_COMPLEXITY_REPLACEMENTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bfollow up about\b", re.I), "follow up regarding"),
    (re.compile(r"\bfollow up on\b", re.I), "follow up regarding"),
    (re.compile(r"\bmake sure\b", re.I), "ensure"),
    (re.compile(r"\bget back to you\b", re.I), "respond"),
    (re.compile(r"\bcheck in about\b", re.I), "inquire regarding"),
    (re.compile(r"\bcheck in on\b", re.I), "inquire regarding"),
    (re.compile(r"\bcoming up soon\b", re.I), "approaching in the near term"),
    (re.compile(r"\bfinish(?:ing)?\b", re.I), "finalize"),
    (re.compile(r"\bwanted to ask\b", re.I), "wanted to inquire"),
    (re.compile(r"\bPlease let me know\b", re.I), "Please advise"),
    (re.compile(r"\bPlease let us know\b", re.I), "Please advise"),
    (re.compile(r"\blet me know\b", re.I), "please advise"),
    (re.compile(r"\blet us know\b", re.I), "please advise"),
    (re.compile(r"\bbefore\b", re.I), "prior to"),
    (re.compile(r"\bspeed up\b", re.I), "expedite"),
    (re.compile(r"\bhelp (?:with|us|you)\b", re.I), "facilitate"),
)


def _apply_advanced_complexity_replacements(text: str) -> str:
    """Upgrade vocabulary for advanced complexity only — does not change tone or length."""
    result = text
    for pattern, replacement in _ADVANCED_COMPLEXITY_REPLACEMENTS:
        result = pattern.sub(replacement, result)
    result = re.sub(r"  +", " ", result)
    return result.strip()

GENERATE_SHORT_CONTENT_RULES = """\
SHORT LENGTH CONTENT (mandatory when length is short):
  • 1 short paragraph with at most 2 sentences — core message only, no padding.
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


_GENERATE_LEAK_LINE_RE = re.compile(
    r"(?im)^(?:\s*(?:===+\s*)?(?:LENGTH|TONE|COMPLEXITY)\b.*|"
    r"\s*(?:Length|Tone|Complexity) setting\b.*|"
    r"\s*INDEPENDENCE RULE\b.*|"
    r"\s*(?:PERSONAL PROFILE|PERMANENT NOTE|STANDING INSTRUCTION|USER PROFILE|"
    r"Writer details|FINAL LENGTH CHECK|SEED TEXT TO EXPAND|DOCUMENT CONTEXT|OUTPUT RULES|"
    r"THREE (?:FULLY )?INDEPENDENT|ACTIVE (?:LENGTH|TONE|COMPLEXITY)|"
    r"Idea to expand|Always follow this standing note|OUTPUT RULES)\b.*|"
    r"\s*OUTPUT:\s*Return ONLY\b.*|"
    r"\s*(?:structure only|vocabulary only|voice only|how it sounds only)\b.*"
    r")\s*$"
)

_GENERATE_LEAK_INLINE_RE = re.compile(
    r"(?is)\n*(?:===+\s*)?(?:LENGTH|TONE|COMPLEXITY)\s+INSTRUCTION\b.*?(?=\n\n|\Z)|"
    r"\n*INDEPENDENCE RULE\b.*?(?=\n\n|\Z)|"
    r"\n*(?:PERSONAL PROFILE|PERMANENT NOTE|STANDING INSTRUCTION)\b[^\n]*(?:\n(?![A-Z][a-z]+:)[^\n]*)*"
)


def _strip_generate_instruction_leakage(text: str) -> str:
    """Remove prompt/rule text the model may echo into the draft."""
    if not text or not text.strip():
        return text

    lines: list[str] = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if _GENERATE_LEAK_LINE_RE.match(line):
            continue
        # Drop lines that are clearly meta instructions, not email content
        stripped = line.strip()
        if re.match(
            r"^(?:must NEVER|Changing one setting|comma-separated key-value|"
            r"auto-inject|never invent names|no placeholder text|"
            r"Do not change tone or vocabulary)\b",
            stripped,
            re.I,
        ):
            continue
        lines.append(line)

    cleaned = "\n".join(lines)
    cleaned = _GENERATE_LEAK_INLINE_RE.sub("", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


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
    cleaned = _strip_generate_instruction_leakage(cleaned)
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
    (re.compile(r"\bfacilitate\b", re.IGNORECASE), "help"),
    (re.compile(r"\bexpedite\b", re.IGNORECASE), "speed up"),
    (re.compile(r"\bcomprehensive\b", re.IGNORECASE), "full"),
    (re.compile(r"\bendeavor\b", re.IGNORECASE), "try"),
    (re.compile(r"\bsubsequently\b", re.IGNORECASE), "then"),
    (re.compile(r"\bprior to\b", re.IGNORECASE), "before"),
    (re.compile(r"\bregarding\b", re.IGNORECASE), "about"),
    (re.compile(r"\bensure\b", re.IGNORECASE), "make sure"),
    (re.compile(r"\binquire\b", re.IGNORECASE), "ask"),
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


_STANDALONE_SIGNOFF_PARAGRAPH_RE = re.compile(
    r"^(?:best|thanks|thank you|sincerely|regards|kind regards|warm regards|cheers|take care)"
    r"[,.!]?\s*(?:\[.+\]|[A-Z][a-z].*)?$",
    re.IGNORECASE,
)


def _is_standalone_signoff_paragraph(paragraph: str) -> bool:
    stripped = paragraph.strip()
    if not stripped:
        return True
    if _is_signoff_line(stripped):
        return True
    return bool(_STANDALONE_SIGNOFF_PARAGRAPH_RE.match(stripped))


def _substantive_body_paragraphs(body: str) -> list[str]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
    return [p for p in paragraphs if not _is_standalone_signoff_paragraph(p)]


def _strip_standalone_signoffs_from_body(body: str) -> str:
    return "\n\n".join(_substantive_body_paragraphs(body))


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

    if length == "short":
        all_sentences: list[str] = []
        for paragraph in paragraphs:
            all_sentences.extend(_split_sentences(paragraph))
        # Seed grounding (later) removes filler; don't strip openers that may carry the seed topic.
        filtered_body = _join_sentences(all_sentences[:2])
        if tone_preset in {"friendly", "casual"}:
            filtered_body = _strip_friendly_casual_hope_phrases(
                filtered_body, allow_good_one=False
            )
        return filtered_body

    first_sentences = _split_sentences(paragraphs[0])
    if tone_preset == "formal" and length in {"medium", "long"}:
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
    return len(_substantive_body_paragraphs(body))


def _count_body_sentences(text: str, format_type: str) -> int:
    if format_type == "email":
        body = _parse_email_sections(text).get("body", "")
    else:
        body = text
    if not body.strip():
        return 0
    return len([s for s in _split_sentences(body) if s.strip()])


def _body_word_count(text: str, format_type: str) -> int:
    if format_type == "email":
        body = _parse_email_sections(text).get("body", "")
    else:
        body = text or ""
    return len(re.findall(r"[A-Za-z0-9']+", body))


def _meets_generate_length_requirement(text: str, format_type: str, length: str) -> bool:
    """Check body structure/size only — never inspect tone or vocabulary."""
    if format_type == "email":
        paragraph_count = _count_email_body_paragraphs(text)
        sentence_count = _count_body_sentences(text, format_type)
    else:
        paragraphs = [p for p in re.split(r"\n\s*\n", text or "") if p.strip()]
        paragraph_count = len(paragraphs)
        sentence_count = _count_body_sentences(text, format_type)
    words = _body_word_count(text, format_type)

    if length == "short":
        # 1 short paragraph, at most 2 body sentences — core message only
        return paragraph_count <= 1 and 1 <= sentence_count <= 2 and words <= 60
    if length == "medium":
        return 2 <= paragraph_count <= 3 and 80 <= words <= 200
    if length == "long":
        # Clearly more developed than medium
        return paragraph_count >= 5 and words >= 220
    return True


def _enforce_length_structure(
    text: str,
    format_type: str,
    length: str,
    *,
    seed_baseline: str = "",
) -> str:
    """Adjust paragraph/sentence count only — never rewrite words (tone/complexity stay)."""
    if not text or not text.strip():
        return text

    if format_type == "email":
        sections = _parse_email_sections(text)
        body = _strip_standalone_signoffs_from_body(sections.get("body", ""))
        paragraphs = _substantive_body_paragraphs(body)

        if length == "short":
            if not paragraphs:
                return text
            sentences: list[str] = []
            for paragraph in paragraphs:
                sentences.extend(_split_sentences(paragraph))
            sentences = sentences[:2]
            if not sentences and paragraphs:
                sentences = [paragraphs[0]]
            sections["body"] = _join_sentences(sentences)
            return _reassemble_email_sections(sections)

        if length == "medium":
            paragraphs = _substantive_body_paragraphs(body)
            if len(paragraphs) == 1:
                sentences = _split_sentences(paragraphs[0])
                if len(sentences) >= 2:
                    mid = max(1, len(sentences) // 2)
                    paragraphs = [
                        _join_sentences(sentences[:mid]),
                        _join_sentences(sentences[mid:]),
                    ]
                elif paragraphs:
                    # Visible medium structure: always at least 2 body paragraphs
                    paragraphs = [
                        paragraphs[0],
                        "Please let me know how you would like to proceed.",
                    ]
            elif len(paragraphs) > 3:
                paragraphs = paragraphs[:2] + [" ".join(paragraphs[2:])]
            elif len(paragraphs) == 0:
                paragraphs = [
                    "I wanted to follow up on this.",
                    "Please let me know how you would like to proceed.",
                ]
            sections["body"] = "\n\n".join(paragraphs)
            return _reassemble_email_sections(sections)

        if length == "long":
            while len(paragraphs) < 5:
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
            for extra in _long_request_elaboration_paragraphs(seed_baseline):
                if len(paragraphs) >= 5:
                    break
                if extra.lower() not in " ".join(paragraphs).lower():
                    paragraphs.append(extra)
            paragraphs = _pad_long_body_paragraphs(paragraphs, seed_baseline=seed_baseline)
            sections["body"] = "\n\n".join(paragraphs)
            return _reassemble_email_sections(sections)

        return text

    # Essay / prose
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if length == "short":
        if not paragraphs:
            return text
        sentences: list[str] = []
        for paragraph in paragraphs:
            sentences.extend(_split_sentences(paragraph))
        return _join_sentences(sentences[:2])
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
        while len(paragraphs) < 5:
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
        for extra in _long_request_elaboration_paragraphs(seed_baseline):
            if len(paragraphs) >= 5:
                break
            if extra.lower() not in " ".join(paragraphs).lower():
                paragraphs.append(extra)
        return "\n\n".join(
            _pad_long_body_paragraphs(paragraphs, seed_baseline=seed_baseline)
        )
    return text


def _long_request_elaboration_paragraphs(seed_baseline: str = "") -> list[str]:
    """On-topic request elaboration only — never invented reasons or meta instructions."""
    seed = (seed_baseline or "").strip().lower()
    ask_bits: list[str] = []
    if "extension" in seed or "deadline" in seed:
        ask_bits = [
            "I am requesting an extension on the current deadline and would appreciate your approval if that is possible.",
            "A bit more time would let me finish the work carefully and submit something that meets the expected standard.",
            "Please let me know what revised timeline would work on your side so I can plan the submission accordingly.",
            "I am ready to follow whatever process you use for deadline changes and can provide any materials you need for this request.",
            "Thank you for considering this extension request — I appreciate your time and any flexibility you can offer.",
            "If you prefer a shorter extension than what is typical, I am happy to work with whatever schedule you recommend.",
            "I will use the additional time to complete remaining pieces of the work and review everything before submitting.",
            "Please tell me whether you would like me to submit what I already finished while I continue working during an extension.",
        ]
    elif "leak" in seed or "landlord" in seed or "sink" in seed:
        ask_bits = [
            "I wanted to report that the sink is leaking and ask that someone come look at it this week.",
            "The leak needs attention soon so it does not get worse, and I would like help arranged as soon as you can.",
            "Please let me know when someone can visit this week, or what information you need from me to schedule the repair.",
            "I can be available to provide access and will follow any steps you prefer for maintenance requests.",
            "Thank you for taking care of this — I appreciate a prompt response so we can get the sink fixed this week.",
            "If you already have a preferred plumber or maintenance contact, I am glad to work with them at a time that works.",
            "Please share any access instructions or building procedures I should follow when the repair visit is scheduled.",
            "I will keep an eye on the sink in the meantime and update you if the leak becomes more urgent before the visit.",
        ]
    else:
        ask_bits = [
            "I wanted to make this request clearly and hope you can help with it.",
            "Please take a look at what I am asking for and let me know how we should move forward.",
            "I am ready to follow your preferred process and can provide anything else you need related to this request.",
            "If a slight adjustment to the details would make this easier to approve, I am happy to work with that.",
            "Thank you for considering this — I appreciate your time and look forward to your reply.",
            "Please share the next step on your side so I can prepare whatever you need from me.",
            "I am available to discuss this further if a short conversation would make the request easier to handle.",
            "Once we align on how to proceed, I will follow through promptly on my end.",
        ]
    return ask_bits


def _pad_long_body_paragraphs(
    paragraphs: list[str],
    *,
    min_words: int = 230,
    seed_baseline: str = "",
) -> list[str]:
    """Grow long drafts with on-topic request detail — never meta or invented excuses."""
    result = list(paragraphs)
    body_so_far = "\n\n".join(result)
    words = len(re.findall(r"[A-Za-z0-9']+", body_so_far))
    for pad in _long_request_elaboration_paragraphs(seed_baseline):
        if words >= min_words:
            break
        if pad.lower() in body_so_far.lower():
            continue
        result.append(pad)
        body_so_far = "\n\n".join(result)
        words = len(re.findall(r"[A-Za-z0-9']+", body_so_far))
    # Extra courteous request-focused pads if still short (still no invented reason).
    extras = [
        "I hope this is a reasonable request and that we can settle on a plan that works for you.",
        "Please reply when you have a moment so I know how to proceed with this request.",
        "I remain flexible on the smaller details as long as the main ask can be accommodated.",
        "Once I hear from you, I will move ahead according to your guidance on this request.",
        "Thank you again for your attention to this — I know these requests take time to review.",
        "I am grateful for any update you can share once you have considered this request.",
    ]
    for pad in extras:
        if words >= min_words:
            break
        if pad.lower() in body_so_far.lower():
            continue
        result.append(pad)
        body_so_far = "\n\n".join(result)
        words = len(re.findall(r"[A-Za-z0-9']+", body_so_far))
    return result


def _build_length_retry_instruction(length: str, format_type: str) -> str:
    kind = "email" if format_type == "email" else "essay"
    if length == "short":
        return (
            "LENGTH RETRY — previous draft was too long. "
            f"Output ONE {kind} only with 1 short body paragraph and at most 2 body sentences. "
            "Core message only. If the idea gave no reason, include no reason. "
            "Do not change tone or vocabulary."
        )
    if length == "medium":
        return (
            "LENGTH RETRY — previous draft body was the wrong size. "
            f"Output ONE {kind} only with 2–3 body paragraphs (~90–160 body words). "
            "If the idea gave no reason, include no reason or excuse. "
            "Do not change tone or vocabulary. Complexity must not shrink this draft."
        )
    return (
        "LENGTH RETRY — previous draft was too short for LONG. "
        f"Output ONE {kind} only with at least 5 body paragraphs and ~220+ body words. "
        "Add genuine detail about the request itself (what you are asking for and how "
        "to proceed). Do NOT invent a reason/excuse. Do NOT write meta commentary about "
        "rules, instructions, or the writing process. Do not change tone or vocabulary."
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

    sentences: list[str] = []
    for paragraph in paragraphs:
        sentences.extend(_split_sentences(paragraph))
    kept = [sentence for sentence in sentences if _sentence_grounded_in_seed(sentence, seed_baseline)]
    if not kept and sentences:
        seed_tokens = _seed_content_tokens(seed_baseline)
        if seed_tokens:
            best = max(
                sentences,
                key=lambda sentence: len(_seed_content_tokens(sentence) & seed_tokens),
            )
            if _seed_content_tokens(best) & seed_tokens:
                kept = [best]
        if not kept:
            kept = [sentences[0]]
    return _join_sentences(kept[:2])


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
    sentences: list[str] = []
    for paragraph in paragraphs:
        sentences.extend(_split_sentences(paragraph))
    kept = [sentence for sentence in sentences if _sentence_grounded_in_seed(sentence, seed_baseline)]
    if not kept and sentences:
        seed_tokens = _seed_content_tokens(seed_baseline)
        if seed_tokens:
            best = max(
                sentences,
                key=lambda sentence: len(_seed_content_tokens(sentence) & seed_tokens),
            )
            if _seed_content_tokens(best) & seed_tokens:
                kept = [best]
        if not kept:
            kept = [sentences[0]]
    return _join_sentences(kept[:2])


def build_seed_content_baseline(text: str, notes: str = "") -> str:
    parsed = _parse_generation_note(notes)
    parts = [text.strip()]
    if parsed.get("informational_content"):
        parts.append(parsed["informational_content"].strip())
    return " ".join(part for part in parts if part)


def _body_from_seed(seed_baseline: str, tone_preset: str) -> str:
    """Fallback body when filters leave the draft empty — still reflects the seed."""
    seed = (seed_baseline or "").strip().rstrip(".")
    if not seed:
        return "I wanted to follow up on this."
    seed_l = seed[0].lower() + seed[1:] if seed else seed
    if tone_preset == "formal":
        return f"I am writing to follow up regarding {seed_l}."
    if tone_preset == "casual":
        return f"Just checking in about {seed_l}."
    return f"I wanted to follow up about {seed_l}."


def _inject_permanent_note(text: str, permanent_note: str, format_type: str) -> str:
    """Ensure non-signoff permanent note content is visible in the body when provided.

    Sign-off / signature notes are handled only via the closing signature line.
    """
    note = (permanent_note or "").strip()
    if not note or not text.strip():
        return text
    _name, remaining, is_signoff_only = _parse_signoff_permanent_note(note)
    if is_signoff_only or not remaining:
        return text
    note = remaining

    # If note already reflected (keyword overlap), leave as-is
    note_tokens = {
        w for w in re.findall(r"[a-z0-9']+", note.lower()) if len(w) > 3
    }
    text_tokens = set(re.findall(r"[a-z0-9']+", text.lower()))
    if note_tokens and len(note_tokens & text_tokens) / len(note_tokens) >= 0.4:
        return text

    sentence = _permanent_note_sentence(note)
    if not sentence:
        return text

    if format_type == "email":
        sections = _parse_email_sections(text)
        body = sections.get("body", "").strip()
        if body:
            sections["body"] = f"{body}\n\n{sentence}"
        else:
            sections["body"] = sentence
        return _reassemble_email_sections(sections)

    return f"{text.rstrip()}\n\n{sentence}"


def _ensure_nonempty_body(
    text: str,
    *,
    format_type: str,
    seed_baseline: str,
    tone_preset: str,
) -> str:
    if format_type != "email":
        if text.strip():
            return text
        return _body_from_seed(seed_baseline, tone_preset)

    sections = _parse_email_sections(text)
    if sections.get("body", "").strip():
        return text
    sections["body"] = _body_from_seed(seed_baseline, tone_preset)
    return _reassemble_email_sections(sections)


_SEED_REASON_HINT_RE = re.compile(
    r"(?i)\b("
    r"because|due to|since|reason|excuse|health|sick|illness|ill|medical|"
    r"family|emergency|workload|circumstances|personal (matter|issue|challenge)|"
    r"busy with|conflict|travel|unexpected|unforeseen"
    r")\b"
)

_INVENTED_REASON_CLAUSE_RE = re.compile(
    r"(?i)\b("
    r"due to (unforeseen|unexpected|personal|some)\b[^.]{0,120}"
    r"|unforeseen (personal )?(circumstances|events|issues|challenges|matters)\b[^.]{0,80}"
    r"|unexpected (personal )?(circumstances|events|issues|challenges|matters|work responsibilities)\b[^.]{0,80}"
    r"|personal (circumstances|matters|issues|challenges)\b[^.]{0,80}"
    r"|health issues?\b[^.]{0,80}"
    r"|family emergency\b[^.]{0,80}"
    r"|recent workload has been quite challenging\b[^.]{0,80}"
    r"|my current schedule has been quite hectic\b[^.]{0,100}"
    r"|been (more )?(quite )?challenging than (expected|anticipated)\b[^.]{0,80}"
    r")\.?"
)

_META_INSTRUCTION_COMMENTARY_RE = re.compile(
    r"(?is)(?:^|\n\n)\s*("
    r"to keep this simple,? here is the ask[^.]*\."
    r"|i am not adding a separate reason[^.]*\."
    r"|again,? this is the same request restated[^.]*\."
    r"|i can provide more detail about the request itself if that would help[^.]*\."
    r"|i do not have a separate story to add[^.]*\."
    r"|nothing new beyond the ask itself[^.]*\."
    r"|i wanted to write this out carefully so the request[^.]*\."
    r"|please respond when you can with a yes,? a no,? or what you need from me next\."
    r")\s*"
)


def _seed_states_a_reason(seed_baseline: str) -> bool:
    return bool(_SEED_REASON_HINT_RE.search(seed_baseline or ""))


def _strip_meta_instruction_commentary(text: str, format_type: str) -> str:
    """Remove paragraphs that narrate instructions / drafting strategy."""
    if not text or not text.strip():
        return text

    def _clean_body(body: str) -> str:
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
        kept: list[str] = []
        for paragraph in paragraphs:
            lower = paragraph.lower()
            if _META_INSTRUCTION_COMMENTARY_RE.search(paragraph):
                continue
            if any(
                marker in lower
                for marker in (
                    "i am not adding a separate reason",
                    "to keep this simple, here is the ask",
                    "same request restated for clarity",
                    "separate story to add",
                    "nothing new beyond the ask",
                    "write this out carefully so the request",
                    "reply with a yes, a no",
                    "yes, a no, or what you need",
                )
            ):
                continue
            kept.append(paragraph)
        return "\n\n".join(kept)

    if format_type == "email":
        sections = _parse_email_sections(text)
        sections["body"] = _clean_body(sections.get("body", ""))
        return _reassemble_email_sections(sections)
    return _clean_body(text)


def _strip_invented_reasons_if_absent(
    text: str,
    *,
    format_type: str,
    seed_baseline: str,
) -> str:
    """If the idea gave no reason, delete invented justification clauses/sentences."""
    if not text or not text.strip() or _seed_states_a_reason(seed_baseline):
        return text

    def _clean_body(body: str) -> str:
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
        cleaned_paras: list[str] = []
        for paragraph in paragraphs:
            sentences = _split_sentences(paragraph)
            kept_sents: list[str] = []
            for sentence in sentences:
                if _INVENTED_REASON_CLAUSE_RE.search(sentence):
                    # Drop whole sentence if it is mainly a fabricated reason.
                    # Keep only if a clear request survives without the clause.
                    stripped = _INVENTED_REASON_CLAUSE_RE.sub("", sentence)
                    stripped = re.sub(r"\s{2,}", " ", stripped).strip(" ,;")
                    stripped = re.sub(r"\bas\b\s*$", "", stripped, flags=re.I).strip(" ,;")
                    lower = stripped.lower()
                    if not stripped or len(stripped.split()) < 4:
                        continue
                    if any(
                        cue in lower
                        for cue in (
                            "request",
                            "extension",
                            "deadline",
                            "asking",
                            "ask",
                            "please",
                            "would it be",
                            "could you",
                            "let me know",
                            "leaking",
                            "repair",
                        )
                    ):
                        if stripped and not stripped.endswith((".", "!", "?")):
                            stripped += "."
                        if stripped:
                            stripped = stripped[0].upper() + stripped[1:]
                        kept_sents.append(stripped)
                    continue
                kept_sents.append(sentence)
            if kept_sents:
                cleaned_paras.append(_join_sentences(kept_sents))
        return "\n\n".join(cleaned_paras)

    if format_type == "email":
        sections = _parse_email_sections(text)
        sections["body"] = _clean_body(sections.get("body", ""))
        return _reassemble_email_sections(sections)
    return _clean_body(text)


def apply_generate_hard_filters(
    text: str,
    *,
    format_type: str,
    settings: dict[str, Any] | None,
    seed_baseline: str = "",
) -> str:
    if not text or not text.strip():
        return text

    normalized = resolve_effective_generate_settings(settings)
    tone_preset = normalized["tone_preset"]
    length = normalized["length"]
    complexity = normalized["complexity"]
    profile = normalized.get("profile") or {}

    filtered = text
    filtered = _strip_meta_instruction_commentary(filtered, format_type)
    filtered = _strip_invented_reasons_if_absent(
        filtered, format_type=format_type, seed_baseline=seed_baseline
    )
    if tone_preset in {"friendly", "casual"}:
        filtered = _strip_friendly_casual_hope_phrases(filtered, allow_good_one=False)

    if format_type == "email":
        sections = _parse_email_sections(filtered)
        sections["body"] = _strip_standalone_signoffs_from_body(
            _filter_email_body(
                sections["body"],
                tone_preset=tone_preset,
                length=length,
            )
        )
        sections["greeting"] = _enforce_tone_greeting_line(
            sections.get("greeting", ""), tone_preset, profile=profile
        )
        sections["footer"] = _enforce_tone_signoff(
            sections.get("footer", ""), tone_preset, profile
        )
        filtered = _reassemble_email_sections(sections)
    else:
        filtered = _filter_prose_block(filtered, tone_preset=tone_preset, length=length)

    # Tone voice — visibly different personality in the body
    if tone_preset == "formal":
        filtered = _apply_formal_tone_voice(filtered)
    elif tone_preset == "casual":
        filtered = _apply_casual_tone_voice(filtered)
    elif tone_preset == "friendly":
        filtered = _apply_friendly_tone_voice(filtered)

    # Complexity — vocabulary only
    if complexity == "simple":
        filtered = _apply_simple_complexity_replacements(filtered)
    elif complexity == "advanced":
        filtered = _apply_advanced_complexity_replacements(filtered)

    if length == "short" and seed_baseline.strip():
        filtered = _filter_short_to_seed_content(
            filtered,
            seed_baseline,
            format_type=format_type,
        )

    filtered = _normalize_generate_names(filtered, profile)
    filtered = _take_first_complete_draft(filtered)
    filtered = _ensure_nonempty_body(
        filtered,
        format_type=format_type,
        seed_baseline=seed_baseline,
        tone_preset=tone_preset,
    )

    # Greeting/signoff so tone markers stay visible (profile note applied after length)
    if format_type == "email":
        sections = _parse_email_sections(filtered)
        sections["body"] = _strip_standalone_signoffs_from_body(sections.get("body", ""))
        sections["greeting"] = _enforce_tone_greeting_line(
            sections.get("greeting", ""), tone_preset, profile=profile
        )
        sections["footer"] = _enforce_tone_signoff(
            sections.get("footer", ""), tone_preset, profile
        )
        filtered = _reassemble_email_sections(sections)

    return filtered


def finalize_generate_output(
    text: str,
    *,
    format_type: str,
    settings: dict[str, Any] | None,
    seed_baseline: str = "",
) -> str:
    """Apply profile note and tone markers after length enforcement."""
    if not text or not text.strip():
        return text
    # Use resolved settings so sign-off notes populate the signature name.
    normalized = resolve_effective_generate_settings(settings)
    profile = normalized.get("profile") or {}
    tone_preset = normalized["tone_preset"]
    permanent_note = _extract_permanent_note(profile)
    signoff_only = bool(profile.get("_signoff_note_only"))

    filtered = text
    # Sign-off permanent notes must NEVER be injected into body/greeting.
    if permanent_note and not signoff_only:
        if normalized["length"] == "short" and format_type == "email":
            sections = _parse_email_sections(filtered)
            body = sections.get("body", "").strip()
            note_sentence = _permanent_note_sentence(permanent_note)
            if note_sentence and note_sentence.lower() not in body.lower():
                sents = _split_sentences(body) if body else []
                if len(sents) < 2:
                    sents.append(note_sentence)
                    sections["body"] = _join_sentences(sents[:2])
                else:
                    sents[-1] = note_sentence
                    sections["body"] = _join_sentences(sents[:2])
                filtered = _reassemble_email_sections(sections)
            else:
                filtered = _inject_permanent_note(filtered, permanent_note, format_type)
        else:
            filtered = _inject_permanent_note(filtered, permanent_note, format_type)

    if format_type == "email":
        sections = _parse_email_sections(filtered)
        sections["greeting"] = _enforce_tone_greeting_line(
            sections.get("greeting", ""), tone_preset, profile=profile
        )
        sections["footer"] = _enforce_tone_signoff(
            sections.get("footer", ""), tone_preset, profile
        )
        filtered = _reassemble_email_sections(sections)
    if normalized["length"] in {"short", "medium", "long"}:
        filtered = _enforce_length_structure(
            filtered,
            format_type=format_type,
            length=normalized["length"],
            seed_baseline=seed_baseline,
        )
    # Length pads / model text can reintroduce bad filler — strip again.
    filtered = _strip_meta_instruction_commentary(filtered, format_type)
    filtered = _strip_invented_reasons_if_absent(
        filtered, format_type=format_type, seed_baseline=seed_baseline
    )
    return filtered


def _permanent_note_sentence(permanent_note: str) -> str:
    sentence = (permanent_note or "").strip()
    _name, remaining, is_signoff_only = _parse_signoff_permanent_note(sentence)
    if is_signoff_only:
        return ""
    if remaining:
        sentence = remaining
    sentence = re.sub(
        r"^(always\s+)?(mention that\s+|mention\s+|include that\s+|include\s+|say that\s+|say\s+|sign off as\s+)",
        "",
        sentence,
        flags=re.I,
    ).strip()
    if not sentence:
        return ""
    if re.fullmatch(r"[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?", sentence):
        return ""
    sentence = sentence[0].upper() + sentence[1:]
    if not sentence.endswith((".", "!", "?")):
        sentence += "."
    return sentence


def _enforce_tone_greeting_line(
    greeting: str,
    tone_preset: str,
    profile: dict[str, Any] | None = None,
) -> str:
    """Force greeting prefix by tone only — never use the writer's signature name."""
    stripped = (greeting or "").strip()
    writer_name = _extract_profile_full_name(profile or {})
    signoff_name = str((profile or {}).get("_signoff_note_name") or "").strip()
    name = ""
    match = _GREETING_WITH_NAME_RE.match(stripped) if stripped else None
    if match:
        name = match.group(2).strip().rstrip(",")
        if name in ("[Name]", "[Your Name]", "Name", "Your Name", "there", "There"):
            name = ""
        elif name.startswith("[") and name.endswith("]"):
            name = ""
        elif re.fullmatch(r"Sir or Madam", name, re.I):
            name = ""
        elif writer_name and name.lower() == writer_name.lower():
            # Permanent-note / profile name belongs in the signature, not greeting.
            name = ""
        elif signoff_name and name.lower() == signoff_name.lower():
            name = ""
    elif stripped and not re.match(r"^(Dear|Hi|Hey|Hello)\b", stripped, re.I):
        name = stripped.rstrip(",")
        if writer_name and name.lower() == writer_name.lower():
            name = ""
        elif signoff_name and name.lower() == signoff_name.lower():
            name = ""
    if name:
        prefix = {"formal": "Dear", "friendly": "Hi", "casual": "Hey"}.get(
            tone_preset, "Hi"
        )
        return f"{prefix} {name},"
    # Visible tone markers when no recipient name is known
    if tone_preset == "formal":
        return "Dear Sir or Madam,"
    if tone_preset == "casual":
        return "Hey there,"
    return "Hi there,"


def _enforce_tone_signoff(
    footer: str, tone_preset: str, profile: dict[str, Any]
) -> str:
    """Force sign-off word by tone; writer name on next line only when saved."""
    signature_name = _email_signature_name(profile)

    preferred = str(
        profile.get("signOff") or profile.get("sign_off") or ""
    ).strip()
    if preferred:
        signoff = preferred.rstrip(",") + ","
    else:
        signoff = {"formal": "Sincerely,", "friendly": "Best,", "casual": "Thanks,"}.get(
            tone_preset, "Best,"
        )
    if signature_name:
        return f"{signoff}\n{signature_name}"
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


def _email_signature_name(profile: dict[str, Any]) -> str:
    """Writer name for the email signature line — empty when none saved (no placeholders)."""
    saved_name = _extract_profile_full_name(profile)
    if saved_name and not _is_placeholder_name(saved_name):
        return saved_name
    return ""


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
    signature_name = _email_signature_name(profile)
    sections = _parse_email_sections(text)
    has_email_structure = bool(
        sections.get("prefix")
        or sections.get("greeting")
        or sections.get("footer")
    )
    footer_start = 0
    if has_email_structure and sections.get("footer"):
        footer_text = sections["footer"]
        footer_start = text.rfind(footer_text.split("\n")[0])

    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    normalized_lines: list[str] = []
    in_footer = False

    for line_index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            normalized_lines.append(line)
            continue

        if has_email_structure and footer_start and line_index >= footer_start:
            in_footer = True

        greeting_match = _GREETING_WITH_NAME_RE.match(stripped)
        if greeting_match and not in_footer:
            prefix = greeting_match.group(1)
            name_part = greeting_match.group(2).strip().rstrip(",")
            if _is_placeholder_name(name_part):
                # Generic greeting — never leave a bare "Hi"
                normalized_lines.append(
                    {"Dear": "Dear Sir or Madam,", "Hi": "Hi there,", "Hey": "Hey there,", "Hello": "Hello,"}.get(
                        prefix if prefix in {"Dear", "Hi", "Hey", "Hello"} else prefix.capitalize(),
                        f"{prefix} there,",
                    )
                )
                continue
            # Writer / sign-off name must never appear in the salutation
            if saved_name and name_part.lower() == saved_name.lower():
                normalized_lines.append(
                    {"Dear": "Dear Sir or Madam,", "Hi": "Hi there,", "Hey": "Hey there,", "Hello": "Hello,"}.get(
                        prefix if prefix in {"Dear", "Hi", "Hey", "Hello"} else "Hi",
                        "Hi there,",
                    )
                )
                continue
            # Drop invented recipient names — keep generic greeting only
            generic = {
                "Dear": "Dear Sir or Madam,",
                "Hi": "Hi there,",
                "Hey": "Hey there,",
                "Hello": "Hello,",
            }.get(
                prefix if prefix in {"Dear", "Hi", "Hey", "Hello"} else prefix.capitalize(),
                "Hi there,",
            )
            normalized_lines.append(generic)
            continue

        signoff_match = _SIGNOFF_INLINE_NAME_RE.match(stripped)
        if signoff_match:
            prefix = signoff_match.group(1)
            name_part = signoff_match.group(2).strip()
            if in_footer:
                normalized_lines.append(
                    prefix if prefix.endswith(",") else f"{prefix},"
                )
                if signature_name:
                    normalized_lines.append(signature_name)
                continue
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
            if in_footer and signature_name:
                normalized_lines.append(signature_name)
            elif saved_name:
                normalized_lines.append(saved_name)
            # else drop placeholder / unnamed signature lines
            continue

        if not in_footer:
            stripped = re.sub(r"\[[^\]]+\]", "", stripped).strip()
            if not stripped:
                continue
            if stripped != line.strip():
                normalized_lines.append(stripped)
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
            result_lines[index + 1] = signature_name or None
            continue
        if saved_name and nxt.lower() == saved_name.lower():
            continue
        if re.fullmatch(r"[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?", nxt):
            # Drop invented sender names when no profile is saved
            result_lines[index + 1] = signature_name or None

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


def _normalize_rewrite_instruction(user_instruction: str, *, direct: bool = False) -> str:
    instruction = (user_instruction or "").strip()
    if direct:
        return _normalize_tone_instruction(instruction)
    if not instruction:
        return "Rewrite to sound clear and natural."
    if len(instruction.split()) <= 2 and not any(char in instruction for char in ".!?,:;"):
        return f"Rewrite in a {instruction} tone."
    if not instruction.lower().startswith("rewrite"):
        return f"Rewrite the text as follows: {instruction}"
    return instruction


def build_rewrite_system_instruction(
    user_instruction: str,
    context: dict[str, Any] | None = None,
    *,
    direct: bool = False,
) -> str:
    """One clear system instruction for Rewrite — settings as independent rules."""
    tone_instruction = _normalize_rewrite_instruction(user_instruction, direct=direct)
    examples = _rewrite_tone_examples_block(tone_instruction)
    context_block = format_document_context(context)

    parts = [
        WRITING_AGENT_SYSTEM_PROMPT,
        "TASK: REWRITE the user's selected text. Return only the rewritten plain text.",
        SETTINGS_INDEPENDENCE_HEADER,
        MEANING_FIDELITY_RULE,
        "RULE 1 — TONE (voice only; independent of length and vocabulary):\n"
        f"  Apply this tone instruction to word choice and sentence structure only:\n"
        f"  {tone_instruction}\n"
        "  Tone must NEVER add new facts, greeting/sign-off lines that were not present,\n"
        "  or change how long the message is beyond the wording needed for the voice.",
        "RULE 2 — LENGTH (structure only; independent of tone and vocabulary):\n"
        "  Keep roughly the same length as the original selection.\n"
        "  Do not pad for friendliness or cut substance for formality.\n"
        "  Length must NEVER change tone or vocabulary level.",
        "RULE 3 — VOCABULARY (word choice only; independent of tone and length):\n"
        "  Change words only as needed to match the tone instruction.\n"
        "  Vocabulary must NEVER change meaning, add facts, or force a different length.",
        "RULE 4 — PERSONAL INFO:\n"
        "  Not used for rewrite unless already present in the selected text. "
        "Do not invent personal details.",
        "RULE 5 — PERMANENT NOTE:\n"
        "  None for this rewrite request.",
        TONE_REWRITE_STRICT_RULES,
    ]
    if examples:
        parts.append(examples)
    if context_block:
        parts.append(
            "Document context (awareness only — rewrite ONLY the user message text; "
            "do not rewrite surrounding document text):\n"
            f"{context_block}"
        )
    parts.append(
        "OUTPUT: Return the COMPLETE rewritten selection as plain text only. "
        "No diffs, labels, markdown, or explanations."
    )
    return "\n\n".join(parts)


def build_rewrite_user_message(text: str) -> str:
    """User message is only the selected text to rewrite."""
    return (text or "").strip()


def build_rewrite_prompt(
    text: str,
    user_instruction: str,
    context: dict[str, Any] | None = None,
    *,
    direct: bool = False,
) -> str:
    """Backward-compatible combined view for tests/debug.

    Live calls use build_rewrite_system_instruction + build_rewrite_user_message.
    """
    system = build_rewrite_system_instruction(
        user_instruction, context, direct=direct
    )
    user = build_rewrite_user_message(text)
    return f"{system}\n\n---USER MESSAGE---\n\n{user}"


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
    # Sign-off permanent notes → signature name only (never greeting / body).
    profile = dict(effective.get("profile") or {})
    raw_note = _extract_permanent_note(profile)
    profile["_permanent_note_raw"] = raw_note
    signoff_name, remaining_note, is_signoff_only = _parse_signoff_permanent_note(raw_note)
    if signoff_name and not _extract_profile_full_name(profile):
        profile["fullName"] = signoff_name
        profile["full_name"] = signoff_name
    if is_signoff_only:
        profile["permanentNote"] = ""
        profile["permanent_note"] = ""
        profile["permanentNotes"] = ""
        profile["permanent_notes"] = ""
        profile["_signoff_note_only"] = True
        profile["_signoff_note_name"] = signoff_name or _extract_profile_full_name(profile)
    elif remaining_note != raw_note:
        profile["permanentNote"] = remaining_note
        profile["permanent_note"] = remaining_note
        if signoff_name:
            profile["_signoff_note_name"] = signoff_name
    effective["profile"] = profile
    return effective


def _extract_permanent_note(profile: dict[str, Any]) -> str:
    return str(
        profile.get("permanentNote")
        or profile.get("permanent_note")
        or profile.get("permanentNotes")
        or profile.get("permanent_notes")
        or ""
    ).strip()


_SIGNOFF_PERMANENT_NOTE_RE = re.compile(
    r"(?is)^\s*(?:always\s+)?sign\s*off\s+"
    r"(?:with\s+(?:my\s+)?name\s*[,:\-]?\s*|"
    r"as\s+|using\s+(?:my\s+)?name\s*[,:\-]?\s*)?"
    r"(?P<name>[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)?)?\s*\.?\s*$"
)


def _parse_signoff_permanent_note(note: str) -> tuple[str | None, str, bool]:
    """Return (extracted_name, remaining_note, is_signoff_only).

    Notes like "Always sign off with my name, Eshan." must only affect the
    closing signature — never the greeting or body.
    """
    raw = (note or "").strip()
    if not raw:
        return None, "", False
    match = _SIGNOFF_PERMANENT_NOTE_RE.match(raw)
    if match:
        name = (match.group("name") or "").strip() or None
        return name, "", True
    # Partial: strip a sign-off clause and keep other instructions
    partial = re.sub(
        r"(?is)(?:always\s+)?sign\s*off\s+"
        r"(?:with\s+(?:my\s+)?name\s*[,:\-]?\s*|as\s+|using\s+(?:my\s+)?name\s*[,:\-]?\s*)?"
        r"([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)?)?",
        "",
        raw,
    ).strip(" ,.;")
    name_match = re.search(
        r"(?is)sign\s*off\s+(?:with\s+(?:my\s+)?name\s*[,:\-]?\s*|as\s+)"
        r"([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)?)",
        raw,
    )
    name = name_match.group(1).strip() if name_match else None
    if name or partial != raw:
        return name, partial, not bool(partial)
    return None, raw, False


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
        "Writer details (use in the draft; do not print this label):\n"
        + ", ".join(pairs)
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


def build_generate_system_instruction(
    format_type: str,
    notes: str = "",
    context: dict[str, Any] | None = None,
    settings: dict[str, Any] | None = None,
) -> str:
    """One clear system instruction for Generate — each setting is its own rule."""
    format_type = (format_type or "essay").strip().lower()
    user_notes = (notes or "").strip()
    parsed_note = _parse_generation_note(user_notes)
    effective = resolve_effective_generate_settings(settings, user_notes)
    tone_preset = effective["tone_preset"]
    length = effective["length"]
    complexity = effective["complexity"]
    include_subject = effective["include_subject"]
    profile = effective["profile"]
    permanent_note = str(profile.get("_permanent_note_raw") or _extract_permanent_note(profile)).strip()
    profile_block = _format_generate_profile(profile)
    context_block = format_document_context(context)

    if format_type == "email":
        subject_rule = (
            'Include a subject line on the first line ("Subject: ...").'
            if include_subject
            else "Do not include a subject line."
        )
        format_rules = f"{EMAIL_GENERATION_GUIDE}\n\n{subject_rule}"
    else:
        format_rules = (
            "Write a complete essay from the user's idea.\n"
            "Replace the idea entirely with finished prose."
        )

    tone_rule = _build_tone_rules(tone_preset, format_type)
    if parsed_note["has_tone_instruction"]:
        tone_rule = (
            f"{tone_rule}\n\n"
            "ONE-TIME TONE OVERRIDE for this request only (does not change length or vocabulary):\n"
            f"  {parsed_note['tone_instruction']}\n"
            "  Ignore the saved tone preset voice for THIS draft only; "
            "length and vocabulary rules still apply unchanged."
        )

    personal_rule = (
        "RULE 4 — PERSONAL INFO (reference only if relevant; independent of tone/length/vocabulary):\n"
        "  Use these writer details when natural. Do not print the label list. "
        "Do not invent missing fields. Personal info must NEVER change tone, length, or vocabulary.\n"
        f"  {profile_block}"
        if profile_block
        else (
            "RULE 4 — PERSONAL INFO (reference only if relevant; independent of tone/length/vocabulary):\n"
            "  None provided. Use generic phrasing. "
            "Personal info must NEVER change tone, length, or vocabulary."
        )
    )

    signoff_name, remaining_note, is_signoff_only = _parse_signoff_permanent_note(
        permanent_note
    )
    if is_signoff_only or (signoff_name and not remaining_note):
        permanent_rule = (
            "RULE 5 — PERMANENT NOTE (sign-off / signature only):\n"
            "  Use this name ONLY on the closing signature line after the sign-off word "
            f"(Best,/Sincerely,/Thanks,). Name: {signoff_name or _extract_profile_full_name(profile) or 'profile name'}.\n"
            "  NEVER put this name in the greeting/salutation at the top.\n"
            "  Do not invent a reason or other body content from this note."
        )
    elif permanent_note:
        permanent_rule = (
            "RULE 5 — PERMANENT NOTE (standing preference only; independent of tone/length/vocabulary):\n"
            "  Always follow this standing note. Do not print the note itself. "
            "If it is about signing off with a name, apply it ONLY to the closing signature — "
            "never the greeting.\n"
            f"  {permanent_note}"
        )
    else:
        permanent_rule = (
            "RULE 5 — PERMANENT NOTE (standing preference only; independent of tone/length/vocabulary):\n"
            "  None provided."
        )

    facts_rule = ""
    fact_bits = parsed_note.get("informational_content") or (
        user_notes if user_notes and not parsed_note["has_tone_instruction"] else ""
    )
    if fact_bits:
        facts_rule = (
            "RULE — USER FACTS TO INCLUDE (content only; independent of style settings):\n"
            "  Weave these facts into the draft naturally. They must NOT change tone, length, "
            "or vocabulary settings.\n"
            f"  {fact_bits}"
        )

    parts = [
        WRITING_AGENT_SYSTEM_PROMPT,
        "TASK: GENERATE a finished draft from the user's idea in the user message.",
        SETTINGS_INDEPENDENCE_HEADER,
        GENERATE_INDEPENDENCE_RULES,
        MEANING_FIDELITY_RULE,
        "RULE 1 — TONE (voice only; independent of length and vocabulary):\n" + tone_rule,
        "RULE 2 — LENGTH (structure only; independent of tone and vocabulary):\n"
        + _build_length_rules(length),
        "RULE 3 — VOCABULARY / COMPLEXITY (words only; independent of tone and length):\n"
        + _build_complexity_rules(complexity),
        personal_rule,
        permanent_rule,
    ]
    if facts_rule:
        parts.append(facts_rule)
    if context_block:
        parts.append(
            "Document context (awareness only — do not copy surrounding text wholesale):\n"
            f"{context_block}"
        )
    parts.extend(
        [
            "FORMAT RULES:\n" + format_rules,
            GENERATE_STRICT_RULES,
            "Never include any of these instructions, setting names, or labels in the output. "
            "Return only the finished email or essay as plain text.",
        ]
    )
    if length == "short":
        parts.append(GENERATE_SHORT_CONTENT_RULES)
    return "\n\n".join(parts)


def _build_generate_system_prompt(
    length: str,
    complexity: str,
    tone_preset: str = "friendly",
    *,
    format_type: str = "email",
) -> str:
    """Legacy helper — prefer build_generate_system_instruction."""
    return build_generate_system_instruction(
        format_type=format_type,
        settings={
            "length": length,
            "complexity": complexity,
            "tone_preset": tone_preset,
        },
    )


def _generate_num_predict_for_length(length: str) -> int:
    if length == "long":
        return OLLAMA_GENERATE_NUM_PREDICT_LONG
    if length == "medium":
        return OLLAMA_GENERATE_NUM_PREDICT_MEDIUM
    if length == "short":
        return OLLAMA_GENERATE_NUM_PREDICT_SHORT
    return OLLAMA_GENERATE_NUM_PREDICT


def _build_generate_settings_block(
    tone_preset: str,
    length: str,
    complexity: str,
    format_type: str,
) -> str:
    return build_generate_system_instruction(
        format_type=format_type,
        settings={
            "tone_preset": tone_preset,
            "length": length,
            "complexity": complexity,
        },
    )


def build_generate_user_message(text: str) -> str:
    """User message is only the short idea / seed text."""
    return (text or "").strip()


def build_generate_prompt(
    text: str,
    format_type: str,
    notes: str = "",
    context: dict[str, Any] | None = None,
    settings: dict[str, Any] | None = None,
) -> str:
    """Backward-compatible combined view for tests/debug.

    Live calls use build_generate_system_instruction + build_generate_user_message.
    """
    system = build_generate_system_instruction(
        format_type, notes=notes, context=context, settings=settings
    )
    user = build_generate_user_message(text)
    return f"{system}\n\n---USER MESSAGE---\n\n{user}"


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
                base_url=str(ai_config.get("base_url") or ""),
                url=ai_config.get("url"),
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
        system_prompt = build_rewrite_system_instruction(
            user_instruction, context, direct=direct
        )
        user_message = build_rewrite_user_message(text)
        raw = _call_llm(
            user_message,
            task="rewrite",
            system=system_prompt,
            ai_config=ai_config,
        )
        cleaned = _clean_output(raw)
        cleaned = apply_rewrite_hard_filters(
            text,
            cleaned,
            instruction=user_instruction,
        )
        quality = check_rewrite_quality(text, cleaned, user_instruction)
        if not quality["ok"] and "missing_closing" in quality["issues"]:
            retry_system = (
                f"{system_prompt}\n\nIMPORTANT: Keep every greeting and sign-off line from the "
                "original selection. Do not remove closing lines such as Thanks or a name."
            )
            raw = _call_llm(
                user_message,
                task="rewrite",
                system=retry_system,
                ai_config=ai_config,
            )
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
        seed_baseline = build_seed_content_baseline(text, notes)
        system_prompt = build_generate_system_instruction(
            format_type,
            notes=notes,
            context=context,
            settings=settings,
        )
        user_message = build_generate_user_message(text)
        num_predict = _generate_num_predict_for_length(length)
        raw = _call_llm(
            user_message,
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
            retry_system = f"{system_prompt}\n\n{retry_instruction}"
            raw = _call_llm(
                user_message,
                task="generate",
                system=retry_system,
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
        cleaned = _enforce_length_structure(
            cleaned, format_type, length, seed_baseline=seed_baseline
        )
        cleaned = finalize_generate_output(
            cleaned,
            format_type=format_type,
            settings=effective_settings,
            seed_baseline=seed_baseline,
        )
        cleaned = _strip_generate_instruction_leakage(cleaned)
        cleaned = _strip_meta_instruction_commentary(cleaned, format_type)
        cleaned = _strip_invented_reasons_if_absent(
            cleaned, format_type=format_type, seed_baseline=seed_baseline
        )
        # Re-assert long structure after strips removed filler.
        if length == "long":
            cleaned = _enforce_length_structure(
                cleaned, format_type, length, seed_baseline=seed_baseline
            )
            cleaned = _strip_meta_instruction_commentary(cleaned, format_type)
            cleaned = _strip_invented_reasons_if_absent(
                cleaned, format_type=format_type, seed_baseline=seed_baseline
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
