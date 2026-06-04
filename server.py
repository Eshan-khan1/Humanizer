"""FastAPI server for grammar checking and Ollama humanization."""

from __future__ import annotations

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
OLLAMA_MODEL = "mistral"
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
        "then: ollama pull mistral"
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
    Humanize text via Ollama (mistral).

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


def _build_ollama_grammar_prompt(text: str) -> str:
    rag_block = rag.get_relevant_rules_prompt_block(text, top_k=8)
    rag_section = f"\n{rag_block}\n\n" if rag_block else "\n"

    return f"""You are a strict English grammar and spelling checker. Find EVERY error in the text.

{rag_section}Pass 1 - Spelling & Word Choice:
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
    text: str, errors: list[dict[str, Any]], existing: list[dict[str, Any]]
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

        if any(
            _ranges_overlap(offset, length, m["offset"], m["length"])
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
                offset=offset,
                length=length,
                suggestions=suggestions,
                type=match_type,
                message=message,
                rule_id="OLLAMA_GRAMMAR",
                category="OLLAMA",
            ).model_dump()
        )

    return matches


def _call_mistral_for_grammar(
    text: str, existing: list[dict[str, Any]] | None = None
) -> tuple[list[dict[str, Any]], bool, str | None, list[dict[str, Any]] | None]:
    """
    Always attempt a Mistral/Ollama grammar check (no pre-check skip).

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
            "server.py:_call_mistral_for_grammar",
            "mistral grammar failed",
            {"error": str(exc)[:300]},
        )
        return [], False, None, None


def _check_grammar_ollama(
    text: str, existing: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], bool, str | None, list[dict[str, Any]] | None]:
    """Primary grammar check via Ollama (always tries Mistral first)."""
    return _call_mistral_for_grammar(text, existing)


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


def _check_grammar_languagetool(text: str) -> list[dict[str, Any]]:
    """Fallback grammar check via LanguageTool."""
    tool = _get_language_tool()
    raw_matches = tool.check(text)

    formatted_matches: list[dict[str, Any]] = []
    for match in raw_matches:
        match_type = _classify_match(match.category, match.ruleId)
        if _is_low_confidence_match(match, match_type):
            continue

        offset = match.offset
        length = match.errorLength
        suggestions = _format_suggestions(match.replacements)

        formatted_matches.append(
            GrammarMatch(
                word=_extract_word(text, offset, length, match),
                offset=offset,
                length=length,
                suggestions=suggestions,
                type=match_type,
                message=match.message,
                rule_id=match.ruleId,
                category=match.category,
            ).model_dump()
        )

    return formatted_matches


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


def check_grammar(
    text: str,
    *,
    ollama_matches: list[dict[str, Any]] | None = None,
    ollama_ok: bool | None = None,
) -> dict[str, Any]:
    """
    Check grammar: Ollama primary, LanguageTool fallback when Ollama is offline.

    When both are available, results are merged (non-overlapping).
    """
    text = text.strip()

    if ollama_matches is None or ollama_ok is None:
        ollama_matches, ollama_ok, _, _ = _check_grammar_ollama(text, [])

    if ollama_ok:
        formatted_matches = list(ollama_matches)
        print("=== MISTRAL OK, MERGING LANGUAGETOOL ===", flush=True)
        try:
            lt_matches = _check_grammar_languagetool(text)
            formatted_matches = _merge_grammar_matches(
                formatted_matches, lt_matches
            )
        except Exception as exc:  # noqa: BLE001
            _debug_log(
                "H1",
                "server.py:check_grammar",
                "languagetool merge skipped",
                {"error": str(exc)[:300]},
            )
        corrected = _lightweight_corrected_text(text, formatted_matches)
    else:
        print("=== MISTRAL FAILED, LANGUAGETOOL FALLBACK ===", flush=True)
        formatted_matches = _check_grammar_languagetool(text)
        corrected = _lightweight_corrected_text(text, formatted_matches)

    formatted_matches.sort(key=lambda m: m["offset"])

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
    """Preload mistral so the first user grammar check is faster."""
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
        print("=== GRAMMAR (Mistral) ===", text[:200], flush=True)
    ollama_matches, ollama_ok, raw_response, _errors = _call_mistral_for_grammar(text)
    if DEBUG_OLLAMA:
        print("=== MISTRAL RETURNED ===", (raw_response or "")[:500], flush=True)

    try:
        result = check_grammar(text, ollama_matches=ollama_matches, ollama_ok=ollama_ok)
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
