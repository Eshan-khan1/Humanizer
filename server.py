"""FastAPI server for grammar checking and Ollama humanization."""

from __future__ import annotations

import difflib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import warnings
from contextlib import asynccontextmanager
import urllib.error
import urllib.request
from functools import lru_cache
from typing import Any

import language_tool_python
import requests
import uvicorn

import rag
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

OLLAMA_BASE_URL = "http://127.0.0.1:11434"
OLLAMA_MODEL = "qwen2.5:7b"
OLLAMA_TEMPERATURE = 0.9
OLLAMA_GRAMMAR_TEMPERATURE = 0.2
OLLAMA_START_TIMEOUT_SEC = 30.0
OLLAMA_REQUEST_TIMEOUT_SEC = 120.0
OLLAMA_KEEP_ALIVE = os.environ.get("OLLAMA_KEEP_ALIVE", "30m")
OLLAMA_GRAMMAR_NUM_PREDICT = int(os.environ.get("OLLAMA_GRAMMAR_NUM_PREDICT", "768"))
OLLAMA_GRAMMAR_NUM_CTX = int(os.environ.get("OLLAMA_GRAMMAR_NUM_CTX", "4096"))
DEBUG_OLLAMA = os.environ.get("HUMANIZER_DEBUG_OLLAMA", "").lower() in ("1", "true", "yes")

HOST = "127.0.0.1"
PORT = 8000
DEBUG_LOG_PATH = "/Users/eshankhan/Documents/code/Humanizer/.cursor/debug-2bb802.log"

LANGUAGE_CODE = "en-US"
MIN_SUGGESTIONS = 1
# Skip hint-only rules and uncertain non-spelling matches (contextForSureMatch == 0).
LOW_CONFIDENCE_ISSUE_TYPES = frozenset({"hint"})
UNCERTAIN_GRAMMAR_CATEGORIES = frozenset({
    "STYLE",
    "REDUNDANCY",
    "CLARITY",
    "CREATIVE_WRITING",
    "PLAIN_ENGLISH",
})

_ollama_process: subprocess.Popen[bytes] | None = None


def _debug_log(hypothesis_id: str, location: str, message: str, data: dict | None = None) -> None:
    # #region agent log
    try:
        payload = {
            "sessionId": "2bb802",
            "hypothesisId": hypothesis_id,
            "location": location,
            "message": message,
            "data": data or {},
            "timestamp": int(time.time() * 1000),
        }
        with open(DEBUG_LOG_PATH, "a", encoding="utf-8") as log_file:
            log_file.write(json.dumps(payload) + "\n")
    except OSError:
        pass
    # #endregion


class OllamaError(Exception):
    """Ollama is unavailable, failed to start, or returned an error."""


class TextRequest(BaseModel):
    text: str = Field(..., min_length=1)


class GrammarMatch(BaseModel):
    word: str
    offset: int
    length: int
    suggestions: list[str]
    type: str  # "spelling" | "grammar"
    message: str = ""
    rule_id: str = ""
    category: str = ""


def _classify_match(category: str, rule_id: str) -> str:
    category_l = category.lower()
    rule_l = rule_id.lower()
    if (
        "typo" in category_l
        or "misspell" in category_l
        or "spelling" in category_l
        or "morfologik" in rule_l
        or "speller" in rule_l
        or "hunspell" in rule_l
    ):
        return "spelling"
    return "grammar"


class GrammarResponse(BaseModel):
    text: str
    matches: list[GrammarMatch]
    corrected: str


class HumanizeResponse(BaseModel):
    text: str
    result: str


class HealthResponse(BaseModel):
    ok: bool
    ollama_available: bool
    grammar_available: bool


def _build_ollama_humanize_prompt(text: str) -> str:
    return f"""You are a professional human writer. Rewrite the text below so it sounds like a real person wrote it.

Rules:
- Mix short and long sentences naturally
- Use contractions (it's, don't, you'll)
- Occasionally start sentences with And, But, So
- Add mild filler phrases like "honestly", "to be fair", "the thing is"
- Avoid bullet points, avoid perfect structure
- Use simple everyday vocabulary, avoid fancy words
- Include a tiny imperfection or casual phrasing now and then
- Never sound like a list or an essay
- Keep the original meaning fully intact

Text: {text}

Rewritten (just output the text, nothing else):"""


def _build_casual_second_pass_prompt(text: str) -> str:
    return (
        "Take this text and make it sound more casual and personal. "
        "Vary the rhythm, make it feel like someone speaking directly to the reader. "
        "Output only the rewritten text, nothing else.\n\n"
        f"{text}"
    )


def _split_paragraphs(text: str) -> list[str]:
    """Split text into non-empty paragraphs (blank-line separated)."""
    parts = re.split(r"\n\s*\n", text.strip())
    return [part.strip() for part in parts if part.strip()]


_SENTENCE_SPLIT_RE = re.compile(r"[^.!?]+[.!?]+|[^.!?]+$")
_WORD_TOKEN_RE = re.compile(r"[A-Za-z0-9']+|\S")
_GAP_HINT_RE = re.compile(r'^"([^"]*)"\s*→\s*"([^"]*)"$')


def _split_sentences(text: str) -> list[tuple[int, int, str]]:
    """Return (start, end, sentence_text) spans covering the full text."""
    spans: list[tuple[int, int, str]] = []
    for match in _SENTENCE_SPLIT_RE.finditer(text):
        sentence = match.group().strip()
        if sentence:
            spans.append((match.start(), match.end(), sentence))
    if not spans and text.strip():
        spans.append((0, len(text), text.strip()))
    return spans


def _matches_in_span(
    matches: list[dict[str, Any]], start: int, end: int
) -> list[dict[str, Any]]:
    return [
        match
        for match in matches
        if start <= match.get("offset", -1) < end
    ]


def _phrase_overlaps_match(
    phrase: str, text: str, match: dict[str, Any]
) -> bool:
    phrase_lower = phrase.lower().strip()
    if not phrase_lower:
        return False
    offset = match.get("offset", -1)
    length = match.get("length", 0)
    if not isinstance(offset, int) or not isinstance(length, int):
        return False
    span = text[offset : offset + length].lower()
    return phrase_lower in span or span in phrase_lower


def _lt_covers_phrase(
    phrase: str, text: str, lt_matches: list[dict[str, Any]]
) -> bool:
    return any(_phrase_overlaps_match(phrase, text, match) for match in lt_matches)


def _parse_gap_hint(hint: str) -> tuple[str, str] | None:
    match = _GAP_HINT_RE.match((hint or "").strip())
    if not match:
        return None
    return match.group(1), match.group(2)


def _gap_hints_for_sentence(
    sentence: str, gap_hints: list[str]
) -> list[tuple[str, str]]:
    sentence_lower = sentence.lower()
    found: list[tuple[str, str]] = []
    for hint in gap_hints:
        parsed = _parse_gap_hint(hint)
        if parsed and parsed[0].lower() in sentence_lower:
            found.append(parsed)
    return found


def _sentence_needs_deep_fix(
    sentence: str,
    sentence_start: int,
    sentence_end: int,
    lt_high: list[dict[str, Any]],
    lt_all: list[dict[str, Any]],
    gap_hints: list[str],
    full_text: str,
) -> bool:
    """Route hard sentences to Agent 2 when Agent 1 lacks high-confidence coverage."""
    sent_high = _matches_in_span(lt_high, sentence_start, sentence_end)
    sent_all = _matches_in_span(lt_all, sentence_start, sentence_end)

    for wrong, _correct in _gap_hints_for_sentence(sentence, gap_hints):
        if not _lt_covers_phrase(wrong, full_text, sent_high):
            return True

    if len(sent_all) >= 2:
        return True

    if len(sent_all) > len(sent_high):
        return True

    return False


def _build_deep_fix_prompt(sentence: str, hints: list[str] | None = None) -> str:
    hints = hints or []
    hints_block = ""
    if hints:
        joined = "\n".join(f"- {hint}" for hint in hints)
        hints_block = (
            "Apply these learned corrections where they apply:\n"
            f"{joined}\n\n"
        )

    return (
        "Rewrite this sentence with perfect grammar.\n"
        f"{hints_block}"
        "Return only the corrected sentence, nothing else.\n\n"
        f"{sentence}"
    )


def _clean_deep_fix_response(raw: str) -> str:
    cleaned = (raw or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:\w+)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in {'"', "'"}:
        cleaned = cleaned[1:-1].strip()
    return cleaned


def _tokenize_for_diff(text: str) -> list[str]:
    return _WORD_TOKEN_RE.findall(text)


def _extract_replace_pairs(source: str, reference: str) -> list[tuple[str, str]]:
    source_tokens = _tokenize_for_diff(source)
    reference_tokens = _tokenize_for_diff(reference)
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


def _rewrite_to_matches(
    original: str,
    corrected: str,
    base_offset: int,
    existing: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Turn a full-sentence rewrite into word/phrase-level matches."""
    errors = [
        {"wrong": wrong, "correct": correct, "reason": "Deep sentence rewrite"}
        for wrong, correct in _extract_replace_pairs(original, corrected)
    ]
    return _ollama_errors_to_matches(
        original,
        errors,
        existing=existing,
        base_offset=base_offset,
        rule_id="DEEP_FIXER",
        category="AGENT2",
    )


def _offset_matches_to_sentence(
    matches: list[dict[str, Any]], base_offset: int
) -> list[dict[str, Any]]:
    shifted: list[dict[str, Any]] = []
    for match in matches:
        item = dict(match)
        item["offset"] = int(item.get("offset", 0)) + base_offset
        shifted.append(item)
    return shifted


def _call_deep_fixer(
    sentence: str, *, gap_hints: list[str] | None = None
) -> tuple[str | None, bool]:
    try:
        learned_hints = rag.get_deep_fix_hints(sentence)
        combined_hints: list[str] = []
        seen_hints: set[str] = set()
        for hint in (gap_hints or []) + learned_hints:
            if hint and hint not in seen_hints:
                seen_hints.add(hint)
                combined_hints.append(hint)

        raw = _ollama_generate(
            _build_deep_fix_prompt(sentence, combined_hints),
            temperature=OLLAMA_GRAMMAR_TEMPERATURE,
            grammar=False,
        )
        corrected = _clean_deep_fix_response(raw)
        if corrected and corrected.lower() != sentence.strip().lower():
            return corrected, True
        return corrected or sentence, True
    except (OllamaError, requests.RequestException) as exc:
        _debug_log(
            "H3",
            "server.py:_call_deep_fixer",
            "deep fixer failed",
            {"error": str(exc)[:300]},
        )
        return None, False


def _build_corrected_two_agent(
    text: str,
    sentences: list[tuple[int, int, str]],
    agent1_matches: list[dict[str, Any]],
    deep_fixes: dict[int, str],
) -> str:
    if not agent1_matches and not deep_fixes:
        return text

    parts: list[str] = []
    cursor = 0
    for index, (start, end, sentence) in enumerate(sentences):
        parts.append(text[cursor:start])
        if index in deep_fixes:
            parts.append(deep_fixes[index])
        else:
            sent_matches = _offset_matches_to_sentence(
                [
                    match
                    for match in agent1_matches
                    if start <= match.get("offset", -1) < end
                ],
                -start,
            )
            parts.append(_apply_suggestions_to_text(sentence, sent_matches))
        cursor = end
    parts.append(text[cursor:])
    return "".join(parts)


def _ollama_url(path: str) -> str:
    return f"{OLLAMA_BASE_URL.rstrip('/')}{path}"


def is_ollama_running() -> bool:
    """Return True if the Ollama HTTP API responds."""
    try:
        req = urllib.request.Request(_ollama_url("/api/tags"), method="GET")
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            return resp.status == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def _find_llama_server_binary() -> str | None:
    """Locate llama-server (missing from Homebrew ollama formula 0.30.x)."""
    candidates = [
        "/Applications/Ollama.app/Contents/Resources/lib/ollama/llama-server",
        "/opt/homebrew/Cellar/ollama/0.30.0/libexec/lib/ollama/llama-server",
    ]
    homebrew_cellar = "/opt/homebrew/Cellar/ollama"
    if os.path.isdir(homebrew_cellar):
        for root, _dirs, files in os.walk(homebrew_cellar):
            if "llama-server" in files:
                candidates.insert(0, os.path.join(root, "llama-server"))
    for path in candidates:
        if path and os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return None


def _find_ollama_binary() -> str:
    """
    Prefer the official Ollama.app CLI over the broken Homebrew formula.

    Homebrew `ollama` 0.30.x often lacks `llama-server`; run ./scripts/fix_ollama.sh.
    """
    candidates = [
        "/Applications/Ollama.app/Contents/Resources/ollama",
        shutil.which("ollama"),
    ]
    for path in candidates:
        if path and os.path.isfile(path) and os.access(path, os.X_OK):
            if "/Cellar/ollama/" in path and not _find_llama_server_binary():
                continue
            return path
    raise OllamaError(
        "Ollama is not installed or not on PATH. "
        "Run: ./scripts/fix_ollama.sh  (or install from https://ollama.com) "
        "then: ollama pull qwen2.5:7b"
    )


def _ollama_gpu_env_defaults(env: dict[str, str]) -> dict[str, str]:
    """Apply Metal + unified-memory limits for Apple Silicon (see scripts/ollama_gpu_env.sh)."""
    fraction = float(env.get("OLLAMA_GPU_MEMORY_FRACTION") or "0.75")
    env.setdefault("OLLAMA_GPU_MEMORY_FRACTION", str(fraction))
    env.setdefault("OLLAMA_FLASH_ATTENTION", "1")
    env.setdefault("OLLAMA_LLM_LIBRARY", "metal")
    if sys.platform == "darwin" and not env.get("OLLAMA_GPU_OVERHEAD"):
        try:
            total_mem = int(
                subprocess.check_output(
                    ["sysctl", "-n", "hw.memsize"], text=True
                ).strip()
            )
            env["OLLAMA_GPU_OVERHEAD"] = str(int(total_mem * (1 - fraction)))
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    return env


def _ollama_subprocess_env() -> dict[str, str]:
    """Environment for `ollama serve` so GGUF models find llama-server."""
    env = _ollama_gpu_env_defaults(os.environ.copy())
    llama_server = _find_llama_server_binary()
    if llama_server:
        env["LLAMA_SERVER_PATH"] = llama_server
    return env


def start_ollama() -> None:
    """Start `ollama serve` in the background if the API is not up."""
    global _ollama_process

    if is_ollama_running():
        return

    binary = _find_ollama_binary()
    _ollama_process = subprocess.Popen(
        [binary, "serve"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        env=_ollama_subprocess_env(),
    )

    deadline = time.monotonic() + OLLAMA_START_TIMEOUT_SEC
    while time.monotonic() < deadline:
        if is_ollama_running():
            return
        time.sleep(0.5)

    raise OllamaError(
        f"Ollama did not become ready within {OLLAMA_START_TIMEOUT_SEC:.0f}s"
    )


def ensure_ollama_running() -> None:
    """Ensure the local Ollama server is running, starting it if needed."""
    if not is_ollama_running():
        start_ollama()


def _ollama_generate(
    prompt: str,
    *,
    temperature: float = OLLAMA_TEMPERATURE,
    grammar: bool = False,
) -> str:
    """Send a prompt to Ollama and return the model response text."""
    ensure_ollama_running()

    options: dict[str, Any] = {"temperature": temperature}
    if grammar:
        options["num_predict"] = OLLAMA_GRAMMAR_NUM_PREDICT
        options["num_ctx"] = OLLAMA_GRAMMAR_NUM_CTX

    payload: dict[str, Any] = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "keep_alive": OLLAMA_KEEP_ALIVE,
        "options": options,
    }

    if DEBUG_OLLAMA:
        print("=== OLLAMA PAYLOAD ===", payload, flush=True)

    try:
        response = requests.post(
            "http://127.0.0.1:11434/api/generate",
            json=payload,
            timeout=OLLAMA_REQUEST_TIMEOUT_SEC,
        )
        if DEBUG_OLLAMA:
            print("=== OLLAMA STATUS ===", response.status_code, flush=True)
            print("=== OLLAMA RESPONSE ===", response.text, flush=True)
        response.raise_for_status()
        body = response.json()
    except Exception as e:
        print("=== OLLAMA ERROR ===", str(e), flush=True)
        raise OllamaError(str(e)) from e

    if body.get("error"):
        raise OllamaError(str(body["error"]))

    text = (body.get("response") or "").strip()
    if not text:
        raise OllamaError("Ollama returned an empty response")
    return text


def humanize_text(text: str) -> str:
    """
    Humanize text via Ollama (qwen2.5:7b).

    Each paragraph is rewritten with the main prompt, combined, then passed
    through a second casual/personal pass.
    """
    if not text or not text.strip():
        return ""

    paragraphs = _split_paragraphs(text)
    humanized_paragraphs: list[str] = []
    for paragraph in paragraphs:
        prompt = _build_ollama_humanize_prompt(paragraph)
        humanized_paragraphs.append(_ollama_generate(prompt))

    combined = "\n\n".join(humanized_paragraphs)
    second_pass_prompt = _build_casual_second_pass_prompt(combined)
    return _ollama_generate(second_pass_prompt)


def _log_rag_injection(text: str, info: dict[str, Any]) -> None:
    """Print RAG rule selection for each qwen2.5:7b grammar request."""
    preview = text[:80].replace("\n", " ")
    print("=== RAG INJECTION ===", flush=True)
    print(
        f"  grammar_rules.json: {info['total_rules']} total, "
        f"{info.get('eligible_rules', info['total_rules'])} injectable",
        flush=True,
    )
    print(
        f"  selected: {info['selected_count']} rules (top_k=5, mode={info['mode']})",
        flush=True,
    )
    if info.get("gap_hint_count"):
        print(f"  LT gap hints: {info['gap_hint_count']}", flush=True)
    print(
        f"  prompt block: {info['prompt_block_chars']} chars, "
        f"injected={info['injected']}",
        flush=True,
    )
    for rule in info.get("selected_rules") or []:
        category = rule.get("category") or "uncategorized"
        print(
            f"    - [{rule.get('id')}] ({category}) {rule.get('title')}",
            flush=True,
        )
    if not info.get("selected_rules"):
        print("    - (no rules selected — prompt has no RAG block)", flush=True)
    print(f"  text: {preview!r}", flush=True)


def _build_ollama_grammar_prompt(
    text: str, lt_matches: list[dict[str, Any]] | None = None
) -> str:
    lt_matches = lt_matches or []
    rag_block, rag_info = rag.prepare_grammar_rag_for_prompt(
        text, lt_matches, top_k=rag.DEFAULT_TOP_K
    )
    _log_rag_injection(text, rag_info)
    rag_section = f"\n{rag_block}\n\n" if rag_block else "\n"

    focus_note = ""
    if lt_matches:
        focus_note = (
            "LanguageTool has already flagged some issues (listed above). "
            "Find ADDITIONAL errors it missed — especially those marked MUST find.\n\n"
        )

    return f"""You are a strict English grammar and spelling checker. Find EVERY error in the text.

{rag_section}{focus_note}Pass 1 - Spelling & Word Choice:
- Misspelled words
- Homophones (to/too/two, their/there/they're, your/you're)
- Confused words (specific/pacific, aisle/isle, people/peoples)

Pass 2 - Grammar Rules:
- Pronoun order: He and I / She and I — NEVER Me and him / Me and her
- Subject-verb agreement: compound subjects need were (He and I were)
- Adverb vs adjective (heavily not heavy)
- Plural vs singular mistakes

Pass 3 - Punctuation:
- Run-on sentences
- Incorrect semicolons splitting one thought
- Sentence fragments

Return ONLY this JSON, no explanation, no extra text:
{{"errors": [{{"wrong": "exact wrong phrase from text", "correct": "corrected phrase", "reason": "one line explanation"}}]}}

If no errors found return: {{"errors": []}}

Text to check:
{text}
"""


def _parse_ollama_grammar_response(raw: str) -> list[dict[str, Any]]:
    """Parse Ollama JSON grammar response, tolerating markdown fences."""
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned).strip()

    data = json.loads(cleaned)
    errors = data.get("errors", [])
    if not isinstance(errors, list):
        return []
    return [e for e in errors if isinstance(e, dict)]


def _find_text_offset(text: str, fragment: str, start_at: int = 0) -> tuple[int, int] | None:
    if not fragment:
        return None

    search_from = max(0, start_at - 80)
    idx = text.find(fragment, search_from)
    if idx == -1:
        idx = text.lower().find(fragment.lower(), search_from)
    if idx != -1:
        return idx, len(fragment)

    compact = re.sub(r"\s+", " ", fragment).strip()
    if len(compact) >= 2:
        pattern = re.escape(compact).replace(r"\ ", r"\s+")
        match = re.search(pattern, text[search_from:], flags=re.IGNORECASE)
        if match:
            start = search_from + match.start()
            return start, match.end() - match.start()

    return None


def _ranges_overlap(
    a_offset: int, a_length: int, b_offset: int, b_length: int
) -> bool:
    return a_offset < b_offset + b_length and b_offset < a_offset + a_length


def _merge_grammar_matches(
    primary: list[dict[str, Any]], additional: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Append additional matches that do not overlap any match in primary."""
    merged = list(primary)
    for candidate in additional:
        overlaps = any(
            _ranges_overlap(
                candidate["offset"],
                candidate["length"],
                existing["offset"],
                existing["length"],
            )
            for existing in merged
        )
        if not overlaps:
            merged.append(candidate)
    return merged


def _resolve_error_span(
    text: str, error: dict[str, Any], search_from: int
) -> tuple[int, int] | None:
    wrong = (error.get("wrong") or "").strip()
    correct = (error.get("correct") or "").strip()
    if not wrong or not correct:
        return None

    raw_offset = error.get("offset")
    raw_length = error.get("length")
    if isinstance(raw_offset, int) and isinstance(raw_length, int) and raw_length > 0:
        offset = raw_offset
        length = raw_length
        if 0 <= offset < len(text) and text[offset : offset + length] == wrong:
            return offset, length

    found = _find_text_offset(text, wrong, search_from)
    if not found:
        found = _find_text_offset(text, wrong, 0)
    return found


def _ollama_errors_to_matches(
    text: str,
    errors: list[dict[str, Any]],
    existing: list[dict[str, Any]],
    *,
    base_offset: int = 0,
    rule_id: str = "OLLAMA_GRAMMAR",
    category: str = "OLLAMA",
) -> list[dict[str, Any]]:
    """Convert Ollama error objects to GrammarMatch dicts, skipping overlaps."""
    matches: list[dict[str, Any]] = []
    search_from = 0

    for error in errors:
        wrong = (error.get("wrong") or "").strip()
        correct = (error.get("correct") or "").strip()

        span = _resolve_error_span(text, error, search_from)
        if not span:
            continue

        offset, length = span
        search_from = offset + length
        absolute_offset = base_offset + offset

        if any(
            _ranges_overlap(
                absolute_offset,
                length,
                m["offset"],
                m["length"],
            )
            for m in existing + matches
        ):
            continue

        suggestions = _format_suggestions([correct])
        if not suggestions:
            continue

        match_type = (
            "spelling"
            if len(wrong.split()) == 1 and wrong.isalpha()
            else "grammar"
        )

        reason = (error.get("reason") or "").strip()
        message = reason or f'Use "{correct}" instead of "{wrong}"'

        matches.append(
            GrammarMatch(
                word=text[offset : offset + length],
                offset=absolute_offset,
                length=length,
                suggestions=suggestions,
                type=match_type,
                message=message,
                rule_id=rule_id,
                category=category,
            ).model_dump()
        )

    return matches


def _call_ollama_for_grammar(
    text: str,
    existing: list[dict[str, Any]] | None = None,
    *,
    lt_matches: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], bool, str | None, list[dict[str, Any]] | None]:
    """
    qwen2.5:7b grammar check with RAG context (including LanguageTool gaps).

    Returns (matches, success, raw_response, parsed_errors).
    """
    existing = existing or []
    lt_matches = lt_matches or []
    try:
        prompt = _build_ollama_grammar_prompt(text, lt_matches)
        raw_response = _ollama_generate(
            prompt, temperature=OLLAMA_GRAMMAR_TEMPERATURE, grammar=True
        )
        errors = _parse_ollama_grammar_response(raw_response)
        return (
            _ollama_errors_to_matches(text, errors, existing),
            True,
            raw_response,
            errors,
        )
    except (OllamaError, json.JSONDecodeError, KeyError, TypeError) as exc:
        _debug_log(
            "H3",
            "server.py:_call_ollama_for_grammar",
            "qwen2.5:7b grammar failed",
            {"error": str(exc)[:300]},
        )
        return [], False, None, None


class HumanizerLanguageTool(language_tool_python.LanguageTool):
    """LanguageTool configured for en-US with picky mode and broad rule coverage."""

    def __init__(self) -> None:
        super().__init__(language=LANGUAGE_CODE)
        self.enable_spellchecking()
        self.disabled_categories.difference_update(
            {"TYPOGRAPHY", "CASING", "TYPOS"}
        )

    def _create_params(self, text: str) -> dict[str, str]:
        params = super()._create_params(text)
        params["language"] = LANGUAGE_CODE
        params["level"] = "picky"
        return params


def _extract_word(text: str, offset: int, length: int, match: Any) -> str:
    if 0 <= offset < len(text) and length > 0:
        return text[offset : offset + length]
    matched = getattr(match, "matchedText", None)
    return matched if matched else ""


def _format_suggestions(replacements: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in replacements:
        value = (item or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
        if len(out) >= 5:
            break
    return out


def _is_low_confidence_match(match: Any, match_type: str) -> bool:
    suggestions = _format_suggestions(getattr(match, "replacements", []) or [])
    if len(suggestions) < MIN_SUGGESTIONS:
        return True

    issue_type = (getattr(match, "ruleIssueType", "") or "").lower()
    if issue_type in LOW_CONFIDENCE_ISSUE_TYPES:
        return True

    return False


@lru_cache(maxsize=1)
def _get_language_tool() -> HumanizerLanguageTool:
    """Local LanguageTool instance (en-US, picky mode, Java 8 via LTP 2.8.1)."""
    _debug_log("H1", "server.py:_get_language_tool", "initializing LanguageTool")
    tool = HumanizerLanguageTool()
    _debug_log("H1", "server.py:_get_language_tool", "LanguageTool ready")
    return tool


def _lt_raw_to_match(text: str, match: Any) -> dict[str, Any]:
    match_type = _classify_match(match.category, match.ruleId)
    offset = match.offset
    length = match.errorLength
    return GrammarMatch(
        word=_extract_word(text, offset, length, match),
        offset=offset,
        length=length,
        suggestions=_format_suggestions(match.replacements),
        type=match_type,
        message=match.message,
        rule_id=match.ruleId,
        category=match.category,
    ).model_dump()


def _check_grammar_languagetool_split(
    text: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (high_confidence, all) LanguageTool matches."""
    tool = _get_language_tool()
    raw_matches = tool.check(text)

    high_confidence: list[dict[str, Any]] = []
    all_matches: list[dict[str, Any]] = []
    for match in raw_matches:
        formatted = _lt_raw_to_match(text, match)
        all_matches.append(formatted)
        match_type = formatted["type"]
        if not _is_low_confidence_match(match, match_type):
            high_confidence.append(formatted)

    return high_confidence, all_matches


def _check_grammar_languagetool(text: str) -> list[dict[str, Any]]:
    """High-confidence LanguageTool matches (Agent 1 fast checker)."""
    high_confidence, _all_matches = _check_grammar_languagetool_split(text)
    return high_confidence


def _apply_suggestions_to_text(
    text: str, matches: list[dict[str, Any]]
) -> str:
    """Apply first suggestion per match from end to start."""
    result = text
    for match in sorted(matches, key=lambda m: m["offset"], reverse=True):
        suggestions = match.get("suggestions") or []
        if not suggestions:
            continue
        offset = match["offset"]
        length = match["length"]
        result = result[:offset] + suggestions[0] + result[offset + length :]
    return result


def check_grammar(text: str) -> dict[str, Any]:
    """
    Two-agent grammar pipeline.

    Agent 1 (fast): LanguageTool high-confidence matches + RAG gap routing.
    Agent 2 (deep): qwen2.5:7b full-sentence rewrite for hard sentences.
    """
    text = text.strip()

    try:
        lt_high, lt_all = _check_grammar_languagetool_split(text)
        print(
            "=== AGENT 1 (LT + RAG) ===",
            f"{len(lt_high)} high-confidence matches",
            f"({len(lt_all)} total LT)",
            flush=True,
        )
    except Exception as exc:  # noqa: BLE001
        lt_high, lt_all = [], []
        _debug_log(
            "H1",
            "server.py:check_grammar",
            "languagetool failed",
            {"error": str(exc)[:300]},
        )

    rag_block, rag_info = rag.prepare_grammar_rag_for_prompt(text, lt_high)
    _log_rag_injection(text, rag_info)

    gap_hints, _gap_rule_ids = rag.find_languagetool_gaps(text, lt_high)
    if gap_hints:
        print(
            "=== RAG GAPS ===",
            f"{len(gap_hints)} patterns LT missed",
            flush=True,
        )

    sentences = _split_sentences(text)
    deep_sentence_indexes: list[int] = []
    for index, (start, end, sentence) in enumerate(sentences):
        if _sentence_needs_deep_fix(
            sentence,
            start,
            end,
            lt_high,
            lt_all,
            gap_hints,
            text,
        ):
            deep_sentence_indexes.append(index)

    agent1_matches: list[dict[str, Any]] = []
    agent2_matches: list[dict[str, Any]] = []
    deep_fixes: dict[int, str] = {}

    for index, (start, end, sentence) in enumerate(sentences):
        if index in deep_sentence_indexes:
            continue
        agent1_matches.extend(_matches_in_span(lt_high, start, end))

    if deep_sentence_indexes:
        print(
            "=== AGENT 2 (deep fixer) ===",
            f"{len(deep_sentence_indexes)} sentence(s)",
            flush=True,
        )

    ollama_ok = True
    for index in deep_sentence_indexes:
        start, _end, sentence = sentences[index]
        sentence_gaps = [
            hint
            for hint in gap_hints
            if _parse_gap_hint(hint)
            and (_parse_gap_hint(hint) or ("", ""))[0].lower() in sentence.lower()
        ]
        corrected, ok = _call_deep_fixer(sentence, gap_hints=sentence_gaps)
        if not ok or not corrected:
            ollama_ok = False
            agent1_matches.extend(
                _matches_in_span(lt_high, sentences[index][0], sentences[index][1])
            )
            continue

        deep_fixes[index] = corrected
        rewrite_matches = _rewrite_to_matches(
            sentence,
            corrected,
            base_offset=start,
            existing=agent1_matches + agent2_matches,
        )
        agent2_matches = _merge_grammar_matches(agent2_matches, rewrite_matches)

    formatted_matches = _merge_grammar_matches(agent1_matches, agent2_matches)
    corrected = _build_corrected_two_agent(
        text, sentences, agent1_matches, deep_fixes
    )

    formatted_matches.sort(key=lambda m: m["offset"])

    if deep_sentence_indexes and ollama_ok:
        print(
            "=== TWO-AGENT MERGE ===",
            f"agent1={len(agent1_matches)} agent2={len(agent2_matches)}",
            flush=True,
        )
    elif not deep_sentence_indexes:
        print("=== AGENT 1 ONLY ===", flush=True)

    return {
        "text": text,
        "matches": formatted_matches,
        "corrected": corrected,
    }


def _get_corrected_text(text: str, matches: list[dict[str, Any]]) -> str:
    try:
        return _get_language_tool().correct(text)
    except Exception:
        return _apply_suggestions_to_text(text, matches)


def _lightweight_corrected_text(text: str, matches: list[dict[str, Any]]) -> str:
    """Fast correction for API clients that only use matches (not full LT rewrite)."""
    if not matches:
        return text
    return _apply_suggestions_to_text(text, matches)


_grammar_available = False

warnings.filterwarnings(
    "ignore",
    message="urllib3 v2 only supports OpenSSL",
    module="urllib3",
)


def _warm_ollama_model() -> None:
    """Preload qwen2.5:7b so the first user grammar check is faster."""
    if not is_ollama_running():
        return
    try:
        _ollama_generate('{"errors":[]}', temperature=0, grammar=True)
        _debug_log("H3", "server.py:_warm_ollama_model", "ollama model warm", {})
    except (OllamaError, json.JSONDecodeError, requests.RequestException) as exc:
        _debug_log(
            "H3",
            "server.py:_warm_ollama_model",
            "ollama warm skipped",
            {"error": str(exc)[:200]},
        )


def startup_warm_grammar() -> None:
    """Initialize LanguageTool once at startup (Java 8 compatible via LTP 2.8.1)."""
    global _grammar_available
    _get_language_tool.cache_clear()
    try:
        _get_language_tool()
        rag.load_rules()
        _grammar_quick_response("Warmup.")
        _warm_ollama_model()
        _grammar_available = True
        _debug_log("H1", "server.py:startup", "grammar ready", {"ltp": "2.8.1"})
    except Exception as exc:  # noqa: BLE001
        _grammar_available = False
        _debug_log(
            "H1",
            "server.py:startup",
            "grammar init failed",
            {"error": str(exc)[:300]},
        )


@asynccontextmanager
async def lifespan(_app: FastAPI):
    startup_warm_grammar()
    yield


app = FastAPI(title="Humanizer API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    global _grammar_available
    ollama_ok = is_ollama_running()
    if not _grammar_available:
        try:
            _get_language_tool.cache_clear()
            _get_language_tool()
            _grammar_available = True
        except Exception:
            _grammar_available = False
    _debug_log(
        "H3",
        "server.py:health",
        "health check",
        {"ollama_available": ollama_ok, "grammar_available": _grammar_available},
    )
    return HealthResponse(
        ok=_grammar_available,
        ollama_available=ollama_ok,
        grammar_available=_grammar_available,
    )


def _grammar_quick_response(text: str) -> GrammarResponse:
    """LanguageTool-only — used for fast inline underlines."""
    matches = _check_grammar_languagetool(text)
    return GrammarResponse(text=text, matches=matches, corrected=text)


# Register /grammar/quick before /grammar so routing is unambiguous.
@app.post("/reload-rules")
def reload_rules() -> dict[str, Any]:
    """Reload grammar_rules.json into the RAG cache (called after auto_tune adds rules)."""
    rag.reload_rules_cache()
    total = len(rag.load_rules())
    injectable = len(rag.injectable_rules())
    return {"ok": True, "total_rules": total, "injectable_rules": injectable}


@app.post("/grammar/quick", response_model=GrammarResponse)
def grammar_quick(body: TextRequest) -> GrammarResponse:
    """Fast LanguageTool-only check for snappy inline underlines."""
    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="text must not be empty")
    try:
        return _grammar_quick_response(text)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/grammar", response_model=GrammarResponse)
def grammar(
    body: TextRequest,
    quick: bool = Query(False, description="Fast LanguageTool-only check"),
) -> GrammarResponse:
    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="text must not be empty")

    if quick:
        return _grammar_quick_response(text)

    if DEBUG_OLLAMA:
        print("=== GRAMMAR (LT→RAG→qwen2.5:7b) ===", text[:200], flush=True)

    try:
        result = check_grammar(text)
        _debug_log(
            "H1",
            "server.py:grammar",
            "grammar ok",
            {"match_count": len(result.get("matches", []))},
        )
    except Exception as exc:  # noqa: BLE001
        _debug_log(
            "H1",
            "server.py:grammar",
            "grammar failed",
            {"error": str(exc)[:300]},
        )
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return GrammarResponse(**result)


@app.post("/humanize", response_model=HumanizeResponse)
def humanize(body: TextRequest) -> HumanizeResponse:
    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="text must not be empty")

    try:
        result = humanize_text(text)
    except OllamaError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return HumanizeResponse(text=text, result=result)


if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT, reload=False)
