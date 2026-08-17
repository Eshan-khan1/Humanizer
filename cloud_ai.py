"""Optional cloud / OpenAI-compatible LLM backend."""

from __future__ import annotations

import os
import threading
import time
from typing import Any, Literal
from urllib.parse import urlparse

import requests

CloudProvider = Literal["groq", "openai", "api"]

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"
DEFAULT_GROQ_MODEL = os.environ.get("THOTH_GROQ_MODEL", "llama-3.3-70b-versatile")
DEFAULT_OPENAI_MODEL = os.environ.get("THOTH_OPENAI_MODEL", "gpt-4o-mini")
DEFAULT_API_MODEL = os.environ.get("THOTH_API_MODEL", DEFAULT_OPENAI_MODEL)
CLOUD_REQUEST_TIMEOUT_SEC = float(os.environ.get("THOTH_CLOUD_TIMEOUT_SEC", "120"))
AI_TEST_TIMEOUT_SEC = float(os.environ.get("THOTH_AI_TEST_TIMEOUT_SEC", "20"))
# Pace cloud calls so long generate sweeps do not trip provider TPM limits.
_CLOUD_MIN_GAP_SEC = float(os.environ.get("THOTH_CLOUD_MIN_GAP_SEC", "2.5"))
_cloud_throttle_lock = threading.Lock()
_last_cloud_request_at = 0.0

_SUPPORTED_PROVIDERS = frozenset({"groq", "openai", "api"})
_ALLOWED_URL_SCHEMES = frozenset({"https", "http"})


class CloudAIError(Exception):
    """Cloud LLM provider failed or is misconfigured."""


def _infer_provider_from_key(api_key: str, base_url: str = "") -> str:
    if base_url.strip():
        return "api"
    if api_key.startswith("gsk_"):
        return "groq"
    return "openai"


def _normalize_chat_completions_url(base_url: str) -> str:
    raw = (base_url or "").strip().rstrip("/")
    if not raw:
        return OPENAI_API_URL
    parsed = urlparse(raw)
    if parsed.scheme not in _ALLOWED_URL_SCHEMES:
        raise CloudAIError("AI base URL must start with http:// or https://")
    if not parsed.netloc:
        raise CloudAIError("AI base URL is invalid")
    if raw.endswith("/chat/completions"):
        return raw
    if raw.endswith("/v1"):
        return f"{raw}/chat/completions"
    return f"{raw}/v1/chat/completions"


# Groq retires models periodically — map stale Settings values to a current default.
_GROQ_MODEL_ALIASES: dict[str, str] = {
    "llama-3.1-8b-instant": DEFAULT_GROQ_MODEL,
    "llama3-8b-8192": DEFAULT_GROQ_MODEL,
    "mixtral-8x7b-32768": DEFAULT_GROQ_MODEL,
}


def _resolve_cloud_model(model: str, resolved_provider: str) -> str:
    cleaned = (model or "").strip()
    if not cleaned:
        return _default_model_for_provider(resolved_provider)
    if resolved_provider == "groq":
        return _GROQ_MODEL_ALIASES.get(cleaned, cleaned)
    return cleaned


def _default_model_for_provider(provider: str) -> str:
    if provider == "groq":
        return DEFAULT_GROQ_MODEL
    if provider == "openai":
        return DEFAULT_OPENAI_MODEL
    return DEFAULT_API_MODEL


def normalize_ai_config(raw: dict[str, Any] | None) -> dict[str, Any] | None:
    if not raw or not isinstance(raw, dict):
        return None
    provider = str(raw.get("provider") or raw.get("aiProvider") or "").strip().lower()
    if provider in {"", "local", "ollama"}:
        return None
    if provider not in _SUPPORTED_PROVIDERS:
        raise CloudAIError(f"Unsupported AI provider: {provider}")
    api_key = str(raw.get("api_key") or raw.get("apiKey") or "").strip()
    if "\x00" in api_key:
        raise CloudAIError("AI API key contains invalid characters")
    if not api_key:
        raise CloudAIError("AI API key is required when using a cloud provider")

    base_url = str(raw.get("base_url") or raw.get("baseUrl") or "").strip()
    if "\x00" in base_url:
        raise CloudAIError("AI base URL contains invalid characters")
    if len(base_url) > 512:
        raise CloudAIError("AI base URL is too long")

    resolved = provider
    if provider == "api":
        resolved = _infer_provider_from_key(api_key, base_url)

    model = str(raw.get("model") or "").strip()
    if not model:
        model = _default_model_for_provider(resolved)
    else:
        model = _resolve_cloud_model(model, resolved)

    if provider == "api" and base_url:
        url = _normalize_chat_completions_url(base_url)
    elif resolved == "groq":
        url = GROQ_API_URL
    else:
        url = OPENAI_API_URL

    return {
        "provider": provider,
        "resolved_provider": resolved,
        "api_key": api_key,
        "model": model,
        "base_url": base_url,
        "url": url,
    }


def _sanitize_provider_error(status_code: int, body: str) -> str:
    if status_code == 401:
        return "AI API key was rejected. Check your key in Settings."
    if status_code == 429:
        return "AI provider rate limit reached. Wait a moment and try again."
    if status_code >= 500:
        lower_body = (body or "").lower()
        if "rate limit" in lower_body or "tokens per" in lower_body or "request too large" in lower_body:
            return "AI provider rate limit reached. Wait a moment and try again."
        return "AI provider is temporarily unavailable. Try again later."
    snippet = body.strip().replace("\n", " ")[:160]
    lower = snippet.lower()
    if "rate limit" in lower or "tokens per" in lower or "request too large" in lower:
        return "AI provider rate limit reached. Wait a moment and try again."
    if "model" in lower and ("not found" in lower or "does not exist" in lower):
        return "AI model is not available for this key. Leave model blank or set a valid model."
    return snippet or f"AI provider request failed ({status_code})"


def _throttle_cloud_requests() -> None:
    """Minimum spacing between cloud completions — avoids consumer-facing 429 storms."""
    global _last_cloud_request_at
    with _cloud_throttle_lock:
        now = time.time()
        wait = _CLOUD_MIN_GAP_SEC - (now - _last_cloud_request_at)
        if wait > 0:
            time.sleep(wait)
        _last_cloud_request_at = time.time()


def call_cloud_chat(
    *,
    provider: CloudProvider | str,
    api_key: str,
    model: str,
    system: str,
    prompt: str,
    temperature: float,
    max_tokens: int,
    base_url: str = "",
    url: str | None = None,
    top_p: float | None = None,
) -> str:
    endpoint = url
    config: dict[str, Any] | None = None
    if not endpoint:
        config = normalize_ai_config(
            {
                "provider": provider,
                "api_key": api_key,
                "model": model,
                "base_url": base_url,
            }
        )
        if not config:
            raise CloudAIError("AI provider is not configured")
        endpoint = config["url"]
        model = config["model"]
    else:
        model = _resolve_cloud_model(
            model,
            _infer_provider_from_key(api_key, base_url),
        )

    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if top_p is not None:
        payload["top_p"] = top_p
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    last_error: Exception | None = None
    for attempt in range(4):
        _throttle_cloud_requests()
        try:
            response = requests.post(
                endpoint,
                headers=headers,
                json=payload,
                timeout=CLOUD_REQUEST_TIMEOUT_SEC,
            )
        except requests.RequestException as exc:
            raise CloudAIError("Could not reach AI API") from exc

        if response.status_code == 429 and attempt < 3:
            delay = min(75.0, 15.0 * (2**attempt))
            time.sleep(delay)
            last_error = CloudAIError(
                _sanitize_provider_error(response.status_code, response.text)
            )
            continue

        # Groq often returns 413/500 with "tokens per minute" / "Request too large".
        if response.status_code in {413, 500, 502, 503} and attempt < 3:
            lower = (response.text or "").lower()
            if "tokens per" in lower or "request too large" in lower or "rate limit" in lower:
                delay = min(75.0, 15.0 * (2**attempt))
                time.sleep(delay)
                last_error = CloudAIError(
                    _sanitize_provider_error(429, response.text)
                )
                continue

        if not response.ok:
            lower = (response.text or "").lower()
            resolved = (
                str(config.get("resolved_provider") or provider)
                if config
                else _infer_provider_from_key(api_key, base_url)
            )
            fallback_model = _default_model_for_provider(resolved)
            if (
                payload["model"] != fallback_model
                and "model" in lower
                and ("not found" in lower or "does not exist" in lower or "decommission" in lower)
            ):
                payload["model"] = fallback_model
                model = fallback_model
                continue
            raise CloudAIError(_sanitize_provider_error(response.status_code, response.text))

        try:
            body = response.json()
            choices = body.get("choices") or []
            message = choices[0].get("message") if choices else {}
            text = str((message or {}).get("content") or "").strip()
        except (AttributeError, IndexError, TypeError, ValueError) as exc:
            raise CloudAIError("AI provider returned an invalid response") from exc

        if not text:
            raise CloudAIError("AI provider returned an empty response")
        return text

    if last_error:
        raise last_error
    raise CloudAIError("AI provider rate limit reached. Wait a moment and try again.")


def test_ai_connection(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Lightweight chat call to verify the API key / endpoint."""
    config = normalize_ai_config(raw)
    if not config:
        raise CloudAIError("Choose API mode and enter an API key first")

    payload = {
        "model": config["model"],
        "messages": [
            {
                "role": "user",
                "content": 'Reply with exactly the word "ok" and nothing else.',
            }
        ],
        "temperature": 0,
        "max_tokens": 8,
    }
    headers = {
        "Authorization": f"Bearer {config['api_key']}",
        "Content-Type": "application/json",
    }
    try:
        response = requests.post(
            config["url"],
            headers=headers,
            json=payload,
            timeout=AI_TEST_TIMEOUT_SEC,
        )
    except requests.RequestException as exc:
        raise CloudAIError("Could not reach AI API") from exc

    if not response.ok:
        raise CloudAIError(_sanitize_provider_error(response.status_code, response.text))

    return {
        "ok": True,
        "provider": config["provider"],
        "model": config["model"],
        "endpoint": config["url"],
    }


def mask_api_key(api_key: str) -> str:
    key = api_key.strip()
    if len(key) <= 8:
        return "****"
    return f"{key[:4]}…{key[-4:]}"
