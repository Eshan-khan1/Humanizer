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
import traceback
import warnings
from contextlib import asynccontextmanager
import urllib.error
import urllib.request
from functools import lru_cache
from typing import Any, Dict, Literal, Optional

import language_tool_python
import requests
import uvicorn

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from cloud_ai import CloudAIError, normalize_ai_config, test_ai_connection
from security import (
    API_TOKEN,
    MAX_NOTES_CHARS,
    MAX_PROFILE_FIELD_CHARS,
    MAX_PROMPT_CHARS,
    MAX_TEXT_CHARS,
    REQUIRE_AUTH,
    LocalClientMiddleware,
    RateLimitMiddleware,
    RequestSizeLimitMiddleware,
    SecurityHeadersMiddleware,
    UntrustedProxyHeadersMiddleware,
    assert_text_length,
    cors_allowed_origins,
    redact_secrets_from_log_data,
    reject_unsafe_text,
    resolve_debug_log_path,
    safe_error_detail,
    sanitize_profile_fields,
    sanitize_ai_config,
    validate_context,
    verify_api_token,
)
from writing_agent import OLLAMA_WRITING_MODEL, generate_text, rewrite_text

OLLAMA_BASE_URL = "http://127.0.0.1:11434"
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "humanizer-grammar")
OLLAMA_GRAMMAR_MODEL = os.environ.get(
    "OLLAMA_GRAMMAR_MODEL", OLLAMA_MODEL
)
OLLAMA_TEMPERATURE = 0.9
OLLAMA_GRAMMAR_TEMPERATURE = 0.2
OLLAMA_START_TIMEOUT_SEC = 30.0
OLLAMA_REQUEST_TIMEOUT_SEC = 120.0
OLLAMA_KEEP_ALIVE = os.environ.get("OLLAMA_KEEP_ALIVE", "30m")
OLLAMA_GRAMMAR_NUM_PREDICT = int(os.environ.get("OLLAMA_GRAMMAR_NUM_PREDICT", "768"))
OLLAMA_GRAMMAR_NUM_CTX = int(os.environ.get("OLLAMA_GRAMMAR_NUM_CTX", "4096"))

GRAMMAR_SYSTEM_PROMPT = (
    "Fix grammar and spelling with minimal, safe edits. Return only the corrected sentence."
)
DEBUG_OLLAMA = os.environ.get("HUMANIZER_DEBUG_OLLAMA", "").lower() in ("1", "true", "yes")

HOST = os.environ.get("HUMANIZER_HOST", "127.0.0.1")
if HOST not in {"127.0.0.1", "localhost"}:
    HOST = "127.0.0.1"
PORT = int(os.environ.get("HUMANIZER_PORT", "8000"))
DEBUG_LOG_PATH = str(resolve_debug_log_path(".cursor/debug-2bb802.log"))

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
    if not DEBUG_OLLAMA:
        return
    try:
        payload = {
            "sessionId": "2bb802",
            "hypothesisId": hypothesis_id,
            "location": location,
            "message": message,
            "data": redact_secrets_from_log_data(data),
            "timestamp": int(time.time() * 1000),
        }
        with open(DEBUG_LOG_PATH, "a", encoding="utf-8") as log_file:
            log_file.write(json.dumps(payload) + "\n")
    except OSError:
        pass


class OllamaError(Exception):
    """Ollama is unavailable, failed to start, or returned an error."""


class AiConfig(BaseModel):
    provider: Literal["local", "ollama", "groq", "openai", "api"] = "local"
    api_key: str = Field("", alias="apiKey", max_length=512)
    model: str = Field("", max_length=128)
    base_url: str = Field("", alias="baseUrl", max_length=512)

    model_config = {"populate_by_name": True}


class TextRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=MAX_TEXT_CHARS)
    ai: Optional[AiConfig] = None


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


class RewriteRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=MAX_TEXT_CHARS)
    prompt: Optional[str] = Field(None, max_length=MAX_PROMPT_CHARS)
    tone: str = Field("neutral", max_length=MAX_PROMPT_CHARS)
    context: Optional[Dict[str, Any]] = None
    ai: Optional[AiConfig] = None


class RewriteResponse(BaseModel):
    text: str
    tone: str
    rewritten: str


class GenerateProfile(BaseModel):
    full_name: str = Field("", alias="fullName", max_length=MAX_PROFILE_FIELD_CHARS)
    sign_off: str = Field("", alias="signOff", max_length=MAX_PROFILE_FIELD_CHARS)
    job_title: str = Field("", alias="jobTitle", max_length=MAX_PROFILE_FIELD_CHARS)
    company_name: str = Field("", alias="companyName", max_length=MAX_PROFILE_FIELD_CHARS)
    school_name: str = Field("", alias="schoolName", max_length=MAX_PROFILE_FIELD_CHARS)
    email: str = Field("", max_length=MAX_PROFILE_FIELD_CHARS)
    phone: str = Field("", max_length=MAX_PROFILE_FIELD_CHARS)
    permanent_note: str = Field("", alias="permanentNote", max_length=MAX_NOTES_CHARS)
    permanent_notes: str = Field("", alias="permanentNotes", max_length=MAX_NOTES_CHARS)

    model_config = {"populate_by_name": True}


class GenerateSettings(BaseModel):
    tone: Optional[str] = Field("warm and friendly", max_length=MAX_PROMPT_CHARS)
    tone_preset: Optional[str] = Field("friendly", alias="tonePreset", max_length=32)
    length: Literal["short", "medium", "long"] = "medium"
    complexity: Literal["simple", "standard", "advanced"] = "standard"
    wording: Optional[Literal["simple", "standard", "advanced"]] = None
    include_subject: bool = Field(True, alias="includeSubject")
    profile: Optional[GenerateProfile] = None

    model_config = {"populate_by_name": True}


class GenerateRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=MAX_TEXT_CHARS)
    format: Literal["email", "essay"] = "essay"
    notes: Optional[str] = Field(None, max_length=MAX_NOTES_CHARS)
    context: Optional[Dict[str, Any]] = None
    settings: Optional[GenerateSettings] = None
    ai: Optional[AiConfig] = None


class GenerateResponse(BaseModel):
    text: str
    format: str
    generated: str


class HealthResponse(BaseModel):
    ok: bool
    ollama_available: bool
    grammar_available: bool
    grammar_model: str = OLLAMA_GRAMMAR_MODEL
    writing_model: str = OLLAMA_WRITING_MODEL
    writing_agent: str = "rewrite, generate"
    cloud_ai_providers: list[str] = ["api", "groq", "openai"]


def _humanize_is_sane(original: str, corrected: str) -> bool:
    """Reject humanize output that drifts too far from the source."""
    if not corrected or not corrected.strip():
        return False
    orig_words = set(re.findall(r"[a-z]+", original.lower()))
    out_words = set(re.findall(r"[a-z]+", corrected.lower()))
    if orig_words:
        overlap = len(orig_words & out_words) / len(orig_words)
        if overlap < 0.45:
            return False
    orig_count = len(original.split())
    out_count = len(corrected.split())
    if orig_count and out_count > max(orig_count * 2, orig_count + 12):
        return False
    return True


def _split_paragraphs(text: str) -> list[str]:
    """Split text into non-empty paragraphs (blank-line separated)."""
    parts = re.split(r"\n\s*\n", text.strip())
    return [part.strip() for part in parts if part.strip()]


_SENTENCE_SPLIT_RE = re.compile(r"[^.!?]+[.!?]+|[^.!?]+$")
_WORD_TOKEN_RE = re.compile(r"[A-Za-z0-9']+|\S")


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


def _sentence_needs_deep_fix(
    sentence_start: int,
    sentence_end: int,
    lt_high: list[dict[str, Any]],
    lt_all: list[dict[str, Any]],
) -> bool:
    """Route hard sentences to Agent 2 when LanguageTool coverage is incomplete."""
    sent_high = _matches_in_span(lt_high, sentence_start, sentence_end)
    sent_all = _matches_in_span(lt_all, sentence_start, sentence_end)

    if len(sent_all) >= 2:
        return True

    if len(sent_all) > len(sent_high):
        return True

    return False


def _build_deep_fix_prompt(sentence: str) -> str:
    return (
        "Fix grammar errors. Rules:\n"
        "- Irregular verbs: buy→bought, go→went, see→saw, run→ran\n"
        '- "i" alone always→"I"\n'
        '- "me and him"→"He and I", "me and her"→"She and I" as ONE phrase\n'
        '- Past tense: "we was"→"we were", "he were"→"he was", "they was"→"they were"\n'
        '- "have seen yesterday"→"saw yesterday" — never use perfect tense with past time words (yesterday, last week, ago)\n'
        '- "don\'t have no"→"don\'t have any", never drop the verb\n'
        '- "their" before a noun is ALWAYS correct, never change to "they\'re" or "there"\n'
        '- "they\'re" means "they are" — only use before a verb\n'
        "- NEVER change a word that was already correctly fixed\n"
        "- NEVER change prepositions (about, with, while, for, of)\n"
        "- No space before punctuation, never split sentences, never add commas unnecessarily\n"
        "- Change only the incorrect phrase(s), not the whole sentence when a short fix suffices\n"
        "- Return ONLY the corrected sentence, nothing else\n"
        "\n"
        "Examples:\n"
        "me and him was going → He and I were going\n"
        "i seen him yesterday → I saw him yesterday\n"
        "we was talking → we were talking\n"
        "she have went yesterday → she went yesterday\n"
        "i don't have no money → I don't have any money\n"
        "their new house → their new house (no change, already correct)\n"
        "they're going → they're going (no change, already correct)\n"
        "\n"
        "Correct this:\n\n"
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


def _strip_bracket_leakage(text: str) -> str:
    """Remove any leftover [bracketed] placeholders the model may have emitted."""
    return re.sub(r"\[[^\]]{0,80}\]", "", text or "").strip()


def _tokenize_for_diff(text: str) -> list[str]:
    return _WORD_TOKEN_RE.findall(text)


def _pairs_from_replace_slice(
    src_slice: list[str], ref_slice: list[str]
) -> list[tuple[str, str]]:
    """Keep each diff replace opcode as one multi-word phrase pair."""
    pairs: list[tuple[str, str]] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(
        None, src_slice, ref_slice
    ).get_opcodes():
        if tag != "replace":
            continue
        sub_src = src_slice[i1:i2]
        sub_ref = ref_slice[j1:j2]
        if not sub_src or not sub_ref:
            continue
        wrong = " ".join(sub_src)
        correct = " ".join(sub_ref)
        if wrong and correct and wrong.lower() != correct.lower():
            pairs.append((wrong, correct))
    return pairs


def _extract_replace_pairs(source: str, reference: str) -> list[tuple[str, str]]:
    source_tokens = _tokenize_for_diff(source)
    reference_tokens = _tokenize_for_diff(reference)
    pairs: list[tuple[str, str]] = []

    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(
        None, source_tokens, reference_tokens
    ).get_opcodes():
        if tag != "replace":
            continue
        pairs.extend(
            _pairs_from_replace_slice(source_tokens[i1:i2], reference_tokens[j1:j2])
        )

    return pairs


def _word_char_spans(text: str, tokens: list[str]) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    pos = 0
    for tok in tokens:
        idx = text.find(tok, pos)
        if idx == -1:
            idx = text.lower().find(tok.lower(), pos)
        if idx == -1:
            spans.append((pos, pos + len(tok)))
            pos += len(tok)
        else:
            spans.append((idx, idx + len(tok)))
            pos = idx + len(tok)
    return spans


def _rewrite_match_word_range(
    original: str, match: dict[str, Any], base_offset: int
) -> tuple[int, int] | None:
    """Map a rewrite match to inclusive word indices in original."""
    local_start = int(match["offset"]) - base_offset
    local_end = local_start + int(match["length"])
    tokens = _tokenize_for_diff(original)
    spans = _word_char_spans(original, tokens)

    first: int | None = None
    last: int | None = None
    for index, (start, end) in enumerate(spans):
        if end <= local_start:
            continue
        if start >= local_end:
            break
        if first is None:
            first = index
        last = index

    if first is None or last is None:
        return None
    return first, last


def _corrected_phrase_for_word_range(
    original: str, corrected: str, word_start: int, word_end: int
) -> str:
    """Aligned phrase from Qwen output covering the same word span."""
    orig_tokens = _tokenize_for_diff(original)
    corr_tokens = _tokenize_for_diff(corrected)
    corr_spans = _word_char_spans(corrected, corr_tokens)

    corr_word_indices: list[int] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(
        None, orig_tokens, corr_tokens
    ).get_opcodes():
        overlap_start = max(i1, word_start)
        overlap_end = min(i2, word_end + 1)
        if overlap_start >= overlap_end:
            continue

        if tag == "equal":
            for orig_index in range(overlap_start, overlap_end):
                corr_word_indices.append(j1 + (orig_index - i1))
        elif tag == "replace":
            orig_len = i2 - i1
            corr_len = j2 - j1
            if orig_len <= 0:
                continue
            for orig_index in range(overlap_start, overlap_end):
                rel = orig_index - i1
                corr_index = j1 + int((rel + 0.5) * corr_len / orig_len)
                corr_index = min(j2 - 1, max(j1, corr_index))
                corr_word_indices.append(corr_index)

    if not corr_word_indices:
        return " ".join(corr_tokens[word_start : word_end + 1])

    c_first = min(corr_word_indices)
    c_last = max(corr_word_indices)
    return corrected[corr_spans[c_first][0] : corr_spans[c_last][1]]


def _merge_rewrite_matches_by_word_gap(
    matches: list[dict[str, Any]],
    original: str,
    corrected: str,
    base_offset: int,
    *,
    max_word_gap: int = 3,
    rule_id: str = "DEEP_FIXER",
    category: str = "AGENT2",
) -> list[dict[str, Any]]:
    """Merge rewrite matches within max_word_gap words of each other."""
    if len(matches) <= 1:
        return matches

    orig_tokens = _tokenize_for_diff(original)
    orig_spans = _word_char_spans(original, orig_tokens)

    indexed: list[tuple[dict[str, Any], tuple[int, int]]] = []
    for match in sorted(matches, key=lambda item: item["offset"]):
        word_range = _rewrite_match_word_range(original, match, base_offset)
        if word_range is None:
            indexed.append((match, (-1, -1)))
        else:
            indexed.append((match, word_range))

    groups: list[list[tuple[dict[str, Any], tuple[int, int]]]] = [[indexed[0]]]
    for item in indexed[1:]:
        _match, (w_start, w_end) = item
        _prev_match, (prev_start, prev_end) = groups[-1][-1]
        if w_start < 0 or prev_start < 0:
            groups.append([item])
            continue
        gap_words = w_start - prev_end - 1
        if gap_words <= max_word_gap:
            groups[-1].append(item)
        else:
            groups.append([item])

    merged: list[dict[str, Any]] = []
    for group in groups:
        if len(group) == 1:
            merged.append(dict(group[0][0]))
            continue

        word_start = min(word_range[0] for _m, word_range in group)
        word_end = max(word_range[1] for _m, word_range in group)
        char_start = orig_spans[word_start][0]
        char_end = orig_spans[word_end][1]
        wrong = original[char_start:char_end]
        suggestion = _corrected_phrase_for_word_range(
            original, corrected, word_start, word_end
        )
        if not wrong or not suggestion or wrong == suggestion:
            merged.extend(dict(m) for m, _ in group)
            continue

        base = dict(group[0][0])
        base.update(
            {
                "word": wrong,
                "offset": base_offset + char_start,
                "length": char_end - char_start,
                "suggestions": _format_suggestions([suggestion]),
                "type": "grammar",
                "message": f'Use "{suggestion}" instead of "{wrong}"',
                "rule_id": rule_id,
                "category": category,
            }
        )
        merged.append(base)

    return merged


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
    matches = _ollama_errors_to_matches(
        original,
        errors,
        existing=existing,
        base_offset=base_offset,
        rule_id="DEEP_FIXER",
        category="AGENT2",
    )
    return _merge_rewrite_matches_by_word_gap(
        matches,
        original,
        corrected,
        base_offset,
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


def _call_deep_fixer(sentence: str) -> tuple[str | None, bool]:
    try:
        raw = _ollama_generate(
            _build_deep_fix_prompt(sentence),
            temperature=OLLAMA_GRAMMAR_TEMPERATURE,
            grammar=True,
            model=OLLAMA_GRAMMAR_MODEL,
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


def _ollama_gpu_env_defaults(env: dict[str, str]) -> dict[str, str]:
    """Apply platform GPU defaults for Ollama (Metal on macOS only)."""
    env.setdefault("OLLAMA_KEEP_ALIVE", "30m")
    env.setdefault("OLLAMA_FLASH_ATTENTION", "1")

    if sys.platform != "darwin":
        # Do not force Metal on Windows/Linux — let Ollama pick CUDA/ROCm/CPU.
        if not os.environ.get("OLLAMA_LLM_LIBRARY"):
            env.pop("OLLAMA_LLM_LIBRARY", None)
        elif env.get("OLLAMA_LLM_LIBRARY") == "metal":
            env.pop("OLLAMA_LLM_LIBRARY", None)
        return env

    fraction = float(env.get("OLLAMA_GPU_MEMORY_FRACTION") or "0.75")
    env.setdefault("OLLAMA_GPU_MEMORY_FRACTION", str(fraction))
    env.setdefault("OLLAMA_LLM_LIBRARY", "metal")
    if not env.get("OLLAMA_GPU_OVERHEAD"):
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


def _find_ollama_binary() -> str:
    """
    Prefer the official Ollama.app CLI on macOS; otherwise use PATH.

    Homebrew `ollama` 0.30.x often lacks `llama-server`; run ./scripts/fix_ollama.sh.
    """
    candidates: list[str | None] = []
    if sys.platform == "darwin":
        candidates.append("/Applications/Ollama.app/Contents/Resources/ollama")
    if sys.platform == "win32":
        local_app = os.environ.get("LOCALAPPDATA", "")
        if local_app:
            candidates.append(os.path.join(local_app, "Programs", "Ollama", "ollama.exe"))
        candidates.append(os.path.expandvars(r"%ProgramFiles%\Ollama\ollama.exe"))
    candidates.append(shutil.which("ollama"))

    for path in candidates:
        if not path:
            continue
        if sys.platform == "win32":
            if os.path.isfile(path):
                return path
        elif os.path.isfile(path) and os.access(path, os.X_OK):
            if "/Cellar/ollama/" in path and not _find_llama_server_binary():
                continue
            return path
    raise OllamaError(
        "Ollama is not installed or not on PATH. "
        "Install from https://ollama.com then restart the terminal. "
        "On macOS you can also run: ./scripts/fix_ollama.sh"
    )


def start_ollama() -> None:
    """Start `ollama serve` in the background if the API is not up."""
    global _ollama_process

    if is_ollama_running():
        return

    binary = _find_ollama_binary()
    popen_kwargs: dict[str, Any] = {
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "env": _ollama_subprocess_env(),
    }
    if sys.platform == "win32":
        # Detach from the console without requiring POSIX start_new_session.
        popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(
            subprocess, "DETACHED_PROCESS", 0
        )
        popen_kwargs["close_fds"] = True
    else:
        popen_kwargs["start_new_session"] = True

    _ollama_process = subprocess.Popen([binary, "serve"], **popen_kwargs)

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
    system: str | None = None,
    model: str | None = None,
    num_predict: int | None = None,
    num_ctx: int | None = None,
) -> str:
    """Send a prompt to Ollama and return the model response text."""
    ensure_ollama_running()

    options: dict[str, Any] = {"temperature": temperature}
    if num_predict is not None:
        options["num_predict"] = num_predict
    elif grammar:
        options["num_predict"] = OLLAMA_GRAMMAR_NUM_PREDICT
    if num_ctx is not None:
        options["num_ctx"] = num_ctx
    elif grammar:
        options["num_ctx"] = OLLAMA_GRAMMAR_NUM_CTX

    payload: dict[str, Any] = {
        "model": model or (OLLAMA_GRAMMAR_MODEL if grammar else OLLAMA_MODEL),
        "prompt": prompt,
        "stream": False,
        "keep_alive": OLLAMA_KEEP_ALIVE,
        "options": options,
    }
    if system is not None:
        payload["system"] = system
    elif grammar:
        payload["system"] = GRAMMAR_SYSTEM_PROMPT

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
        if DEBUG_OLLAMA:
            print("=== OLLAMA ERROR ===", str(e), flush=True)
        raise OllamaError(str(e)) from e

    if body.get("error"):
        raise OllamaError(str(body["error"]))

    text = (body.get("response") or "").strip()
    if not text:
        raise OllamaError("Ollama returned an empty response")
    return text


def humanize_text(text: str, ai_config: dict[str, Any] | None = None) -> str:
    """Fix grammar and spelling — local Ollama or any OpenAI-compatible API."""
    if not text or not text.strip():
        return ""

    paragraphs = _split_paragraphs(text)
    humanized_paragraphs: list[str] = []
    for paragraph in paragraphs:
        try:
            if ai_config:
                from cloud_ai import call_cloud_chat  # noqa: PLC0415

                raw = call_cloud_chat(
                    provider=ai_config["provider"],
                    api_key=ai_config["api_key"],
                    model=ai_config["model"],
                    system=(
                        "You are a grammar correction assistant. Fix grammar and "
                        "spelling with minimal, safe edits. Return only the "
                        "corrected text."
                    ),
                    prompt=_build_deep_fix_prompt(paragraph),
                    temperature=OLLAMA_GRAMMAR_TEMPERATURE,
                    max_tokens=max(128, min(2048, len(paragraph) * 3 + 64)),
                    base_url=str(ai_config.get("base_url") or ""),
                    url=ai_config.get("url"),
                )
            else:
                raw = _ollama_generate(
                    _build_deep_fix_prompt(paragraph),
                    temperature=OLLAMA_GRAMMAR_TEMPERATURE,
                    grammar=True,
                    model=OLLAMA_GRAMMAR_MODEL,
                )
            corrected = _clean_deep_fix_response(raw)
        except CloudAIError:
            raise
        except OllamaError:
            corrected = paragraph
        if not _humanize_is_sane(paragraph, corrected):
            corrected = paragraph
        humanized_paragraphs.append(corrected or paragraph)

    return "\n\n".join(humanized_paragraphs)


def _build_ollama_grammar_prompt(text: str) -> str:
    """Legacy JSON grammar prompt (unused by live two-agent pipeline)."""
    return f"""You are a strict English grammar and spelling checker. Find EVERY error in the text.

Pass 1 - Spelling & Word Choice:
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


def _align_grammar_match(text: str, match: dict[str, Any]) -> dict[str, Any] | None:
    offset = int(match.get("offset", 0) or 0)
    length = int(match.get("length", 0) or 0)
    word = (match.get("word") or "").strip()
    if not word:
        word = match.get("word") or ""
    suggestions = match.get("suggestions") or []
    if not suggestions:
        return None
    suggestion = suggestions[0]

    if length > 0 and 0 <= offset < len(text):
        actual = text[offset : offset + length]
        if actual != (match.get("word") or ""):
            found = _find_text_offset(text, match.get("word") or word, max(0, offset - 80))
            if not found:
                found = _find_text_offset(text, match.get("word") or word, 0)
            if not found:
                return None
            offset, length = found
            actual = text[offset : offset + length]
    else:
        found = _find_text_offset(text, match.get("word") or word, 0)
        if not found:
            return None
        offset, length = found
        actual = text[offset : offset + length]

    if suggestion == actual:
        return None

    aligned = dict(match)
    aligned["offset"] = offset
    aligned["length"] = length
    aligned["word"] = actual
    return aligned


def _align_grammar_matches(text: str, matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    aligned = [_align_grammar_match(text, match) for match in matches]
    return [match for match in aligned if match is not None]


def _homophone_grammar_matches(text: str) -> list[dict[str, Any]]:
    rules: list[tuple[re.Pattern[str], str, str]] = [
        (
            re.compile(r"\bTheir\s+(?=going|coming|not\b|here\b)", re.IGNORECASE),
            "They're",
            "HOMOPHONE_THEIR",
        ),
        (
            re.compile(r"\bYour\s+(?=going|welcome|right\b)", re.IGNORECASE),
            "You're",
            "HOMOPHONE_YOUR",
        ),
        (
            re.compile(r"\bIts\s+(?=a\b|the\b|going)", re.IGNORECASE),
            "It's",
            "HOMOPHONE_ITS",
        ),
        (re.compile(r"\balot\b", re.IGNORECASE), "a lot", "HOMOPHONE_ALOT"),
    ]
    matches: list[dict[str, Any]] = []
    for pattern, replacement, rule_id in rules:
        for found in pattern.finditer(text):
            span = found.group(0)
            start = found.start()
            if rule_id == "HOMOPHONE_ALOT":
                suggestion = replacement
            else:
                suggestion = replacement + span[len(found.group(0).split()[0]) :]
                # span is e.g. "Their " -> prefix "Their", suffix is rest after first word
                first_word = span.split(None, 1)[0] if span.split(None, 1) else span
                rest = span[len(first_word) :]
                suggestion = replacement + rest
            actual = text[start : start + len(span)]
            if suggestion == actual:
                continue
            matches.append(
                {
                    "word": actual,
                    "offset": start,
                    "length": len(actual),
                    "suggestions": [suggestion],
                    "type": "grammar",
                    "message": f'Use "{suggestion.strip()}" instead of "{first_word if rule_id != "HOMOPHONE_ALOT" else actual}"',
                    "rule_id": rule_id,
                    "category": "HOMOPHONE",
                }
            )
    return matches


def _deep_fix_is_sane(original: str, corrected: str) -> bool:
    if not corrected or corrected.strip() == original.strip():
        return False
    if corrected == original:
        return False
    if re.search(r"\.[^\s\n]", corrected):
        return False
    for token in re.findall(r"\S+", corrected):
        if len(token) > 20:
            return False
    return True


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


def _coalesce_nearby_matches(
    text: str,
    matches: list[dict[str, Any]],
    *,
    max_gap: int = 2,
) -> list[dict[str, Any]]:
    """Merge adjacent matches into multi-word fix chunks (not single-word splinters)."""
    if not matches:
        return []

    sorted_matches = sorted(matches, key=lambda m: m["offset"])
    groups: list[list[dict[str, Any]]] = [[sorted_matches[0]]]

    for match in sorted_matches[1:]:
        prev = groups[-1][-1]
        prev_end = prev["offset"] + prev["length"]
        gap = match["offset"] - prev_end
        if gap <= max_gap:
            groups[-1].append(match)
        else:
            groups.append([match])

    coalesced: list[dict[str, Any]] = []
    for group in groups:
        if len(group) == 1:
            coalesced.append(dict(group[0]))
            continue

        start = group[0]["offset"]
        end = group[-1]["offset"] + group[-1]["length"]
        chunk = text[start:end]
        result = chunk
        for item in sorted(group, key=lambda m: m["offset"], reverse=True):
            rel_off = item["offset"] - start
            suggestions = item.get("suggestions") or []
            if not suggestions:
                continue
            result = (
                result[:rel_off]
                + suggestions[0]
                + result[rel_off + item["length"] :]
            )

        base = dict(group[0])
        base.update(
            {
                "offset": start,
                "length": end - start,
                "word": chunk,
                "suggestions": [result],
                "message": f'Use "{result}" instead of "{chunk}"',
                "type": "grammar",
                "rule_id": base.get("rule_id") or "COALESCED",
                "category": base.get("category") or "MERGED",
            }
        )
        coalesced.append(base)

    return coalesced


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
) -> tuple[list[dict[str, Any]], bool, str | None, list[dict[str, Any]] | None]:
    """
    Legacy qwen2.5:7b JSON grammar check (unused by live two-agent pipeline).

    Returns (matches, success, raw_response, parsed_errors).
    """
    existing = existing or []
    try:
        prompt = _build_ollama_grammar_prompt(text)
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

    Agent 1 (fast): LanguageTool high-confidence matches.
    Agent 2 (deep): fine-tuned qwen2.5:7b full-sentence rewrite for hard sentences.
    """
    text = text.strip()

    try:
        lt_high, lt_all = _check_grammar_languagetool_split(text)
        if DEBUG_OLLAMA:
            print(
                "=== AGENT 1 (LT) ===",
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

    sentences = _split_sentences(text)
    deep_sentence_indexes: list[int] = []
    for index, (start, end, _sentence) in enumerate(sentences):
        if _sentence_needs_deep_fix(start, end, lt_high, lt_all):
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
        corrected, ok = _call_deep_fixer(sentence)
        if not ok or not corrected or not _deep_fix_is_sane(sentence, corrected):
            ollama_ok = False
            agent1_matches.extend(
                _matches_in_span(lt_high, sentences[index][0], sentences[index][1])
            )
            continue

        deep_fixes[index] = corrected
        try:
            rewrite_matches = _rewrite_to_matches(
                sentence,
                corrected,
                base_offset=start,
                existing=agent1_matches + agent2_matches,
            )
            agent2_matches = _merge_grammar_matches(agent2_matches, rewrite_matches)
        except Exception:
            if DEBUG_OLLAMA:
                traceback.print_exc()
            agent1_matches.extend(
                _matches_in_span(lt_high, sentences[index][0], sentences[index][1])
            )

    formatted_matches = _merge_grammar_matches(agent1_matches, agent2_matches)
    formatted_matches = _coalesce_nearby_matches(text, formatted_matches)
    corrected = _build_corrected_two_agent(
        text, sentences, agent1_matches, deep_fixes
    )

    formatted_matches.sort(key=lambda m: m["offset"])
    formatted_matches = _merge_grammar_matches(
        formatted_matches, _homophone_grammar_matches(text)
    )
    formatted_matches = _align_grammar_matches(text, formatted_matches)
    formatted_matches.sort(key=lambda m: m["offset"])

    if DEBUG_OLLAMA and deep_sentence_indexes and ollama_ok:
        print(
            "=== TWO-AGENT MERGE ===",
            f"agent1={len(agent1_matches)} agent2={len(agent2_matches)}",
            flush=True,
        )
    elif DEBUG_OLLAMA and not deep_sentence_indexes:
        print("=== AGENT 1 ONLY ===", flush=True)

    if DEBUG_OLLAMA:
        print("=== GRAMMAR MATCHES ===", flush=True)
        print(json.dumps(formatted_matches, ensure_ascii=False), flush=True)

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
    """Preload the grammar model so the first user grammar check is faster."""
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


app = FastAPI(
    title="Humanizer API",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if DEBUG_OLLAMA else None,
    redoc_url="/redoc" if DEBUG_OLLAMA else None,
    openapi_url="/openapi.json" if DEBUG_OLLAMA else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_allowed_origins(),
    allow_origin_regex=r"^chrome-extension://[a-p]{32}$",
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(UntrustedProxyHeadersMiddleware)
app.add_middleware(LocalClientMiddleware)
app.add_middleware(RequestSizeLimitMiddleware)
app.add_middleware(RateLimitMiddleware)


def _secure_endpoint(request: Request) -> None:
    verify_api_token(request)


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
        grammar_model=OLLAMA_GRAMMAR_MODEL,
        writing_model=OLLAMA_WRITING_MODEL,
    )


def _grammar_quick_response(text: str) -> GrammarResponse:
    """LanguageTool-only — used for fast inline underlines."""
    matches = _check_grammar_languagetool(text)
    return GrammarResponse(text=text, matches=matches, corrected=text)


# Register /grammar/quick before /grammar so routing is unambiguous.
@app.post("/reload-rules", dependencies=[Depends(_secure_endpoint)])
def reload_rules() -> dict[str, Any]:
    """No-op kept for auto_tune compatibility (RAG removed from grammar pipeline)."""
    return {"ok": True, "message": "RAG removed; reload not required"}


@app.post("/grammar/quick", response_model=GrammarResponse, dependencies=[Depends(_secure_endpoint)])
def grammar_quick(body: TextRequest) -> GrammarResponse:
    """Fast LanguageTool-only check for snappy inline underlines."""
    text = assert_text_length(body.text, field="text")
    try:
        return _grammar_quick_response(text)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=safe_error_detail(exc)) from exc


@app.post("/grammar", response_model=GrammarResponse, dependencies=[Depends(_secure_endpoint)])
def grammar(
    body: TextRequest,
    quick: bool = Query(False, description="Fast LanguageTool-only check"),
) -> GrammarResponse:
    text = assert_text_length(body.text, field="text")

    if quick:
        return _grammar_quick_response(text)

    if DEBUG_OLLAMA:
        print("=== GRAMMAR (LT→qwen2.5:7b) ===", text[:200], flush=True)

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
        raise HTTPException(status_code=500, detail=safe_error_detail(exc)) from exc

    return GrammarResponse(**result)


@app.post("/humanize", response_model=HumanizeResponse, dependencies=[Depends(_secure_endpoint)])
def humanize(body: TextRequest) -> HumanizeResponse:
    text = assert_text_length(body.text, field="text")

    try:
        ai_config = normalize_ai_config(
            sanitize_ai_config(body.ai.model_dump(by_alias=False) if body.ai else None)
        )
        result = humanize_text(text, ai_config=ai_config)
    except CloudAIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except OllamaError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=safe_error_detail(exc)) from exc

    return HumanizeResponse(text=text, result=result)


class AiTestRequest(BaseModel):
    ai: AiConfig


class AiTestResponse(BaseModel):
    ok: bool
    provider: str = ""
    model: str = ""
    endpoint: str = ""
    detail: str = ""


@app.post("/ai/test", response_model=AiTestResponse, dependencies=[Depends(_secure_endpoint)])
def ai_test(body: AiTestRequest) -> AiTestResponse:
    try:
        cleaned = sanitize_ai_config(body.ai.model_dump(by_alias=False))
        result = test_ai_connection(cleaned)
        return AiTestResponse(
            ok=True,
            provider=str(result.get("provider") or ""),
            model=str(result.get("model") or ""),
            endpoint=str(result.get("endpoint") or ""),
        )
    except CloudAIError as exc:
        return AiTestResponse(ok=False, detail=str(exc))
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, str) else "Invalid AI settings"
        return AiTestResponse(ok=False, detail=detail)
    except Exception as exc:  # noqa: BLE001
        return AiTestResponse(ok=False, detail=safe_error_detail(exc))


@app.post("/rewrite", response_model=RewriteResponse, dependencies=[Depends(_secure_endpoint)])
def rewrite(body: RewriteRequest) -> RewriteResponse:
    text = assert_text_length(body.text, field="text")

    user_prompt = (body.prompt or body.tone or "").strip()
    if not user_prompt:
        raise HTTPException(status_code=400, detail="prompt must not be empty")
    reject_unsafe_text(user_prompt, field="prompt")
    if len(user_prompt) > MAX_PROMPT_CHARS:
        raise HTTPException(status_code=413, detail="prompt exceeds maximum length")
    context = validate_context(body.context)
    direct = bool((body.prompt or "").strip())

    try:
        ai_config = normalize_ai_config(
            sanitize_ai_config(body.ai.model_dump(by_alias=False) if body.ai else None)
        )
        rewritten = rewrite_text(
            text, user_prompt, context, direct=direct, ai_config=ai_config
        )
    except CloudAIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except OllamaError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=safe_error_detail(exc)) from exc

    return RewriteResponse(text=text, tone=user_prompt, rewritten=rewritten)


@app.post("/generate", response_model=GenerateResponse, dependencies=[Depends(_secure_endpoint)])
def generate(body: GenerateRequest) -> GenerateResponse:
    text = assert_text_length(body.text, field="text")

    format_type = (body.format or "essay").strip().lower()
    if format_type not in ("email", "essay"):
        raise HTTPException(status_code=400, detail="format must be 'email' or 'essay'")

    notes = (body.notes or "").strip()
    if notes:
        reject_unsafe_text(notes, field="notes")
        if len(notes) > MAX_NOTES_CHARS:
            raise HTTPException(status_code=413, detail="notes exceeds maximum length")

    try:
        settings = (
            body.settings.model_dump(by_alias=False)
            if body.settings is not None
            else None
        )
        if settings and isinstance(settings.get("profile"), dict):
            settings["profile"] = sanitize_profile_fields(settings["profile"])
        ai_config = normalize_ai_config(
            sanitize_ai_config(body.ai.model_dump(by_alias=False) if body.ai else None)
        )
        generated = generate_text(
            text,
            format_type,
            notes,
            validate_context(body.context),
            settings=settings,
            ai_config=ai_config,
        )
        generated = _strip_bracket_leakage(generated)
    except CloudAIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except OllamaError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=safe_error_detail(exc)) from exc

    return GenerateResponse(text=text, format=format_type, generated=generated)


if __name__ == "__main__":
    if REQUIRE_AUTH and API_TOKEN:
        print("  API auth: enabled (Bearer token required)")
        print(f"  HUMANIZER_API_TOKEN={API_TOKEN}")
    elif not API_TOKEN:
        print("  Security note: set HUMANIZER_REQUIRE_AUTH=1 or HUMANIZER_API_TOKEN for Bearer auth")
    uvicorn.run(app, host=HOST, port=PORT, reload=False)
