"""Optional cloud / OpenAI-compatible LLM backend."""

from __future__ import annotations

import os
from typing import Any, Literal
from urllib.parse import urlparse

import requests

CloudProvider = Literal["groq", "openai", "api"]

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"
DEFAULT_GROQ_MODEL = os.environ.get("HUMANIZER_GROQ_MODEL", "llama-3.3-70b-versatile")
DEFAULT_OPENAI_MODEL = os.environ.get("HUMANIZER_OPENAI_MODEL", "gpt-4o-mini")
DEFAULT_API_MODEL = os.environ.get("HUMANIZER_API_MODEL", DEFAULT_OPENAI_MODEL)
CLOUD_REQUEST_TIMEOUT_SEC = float(os.environ.get("HUMANIZER_CLOUD_TIMEOUT_SEC", "120"))
AI_TEST_TIMEOUT_SEC = float(os.environ.get("HUMANIZER_AI_TEST_TIMEOUT_SEC", "20"))

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
        model = _default_model_for_provider(resolved if provider != "api" else "api")

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
        return "AI API key was rejected. Check your key in extension Settings."
    if status_code == 429:
        return "AI provider rate limit reached. Wait a moment and try again."
    if status_code >= 500:
        return "AI provider is temporarily unavailable. Try again later."
    snippet = body.strip().replace("\n", " ")[:160]
    return snippet or f"AI provider request failed ({status_code})"


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
) -> str:
    endpoint = url
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

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    try:
        response = requests.post(
            endpoint,
            headers=headers,
            json=payload,
            timeout=CLOUD_REQUEST_TIMEOUT_SEC,
        )
    except requests.RequestException as exc:
        raise CloudAIError("Could not reach AI API") from exc

    if not response.ok:
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
