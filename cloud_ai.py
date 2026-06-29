"""Optional cloud LLM backend (Groq / OpenAI-compatible APIs)."""

from __future__ import annotations

import os
from typing import Any, Literal

import requests

CloudProvider = Literal["groq", "openai"]

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"
DEFAULT_GROQ_MODEL = os.environ.get("HUMANIZER_GROQ_MODEL", "llama-3.3-70b-versatile")
DEFAULT_OPENAI_MODEL = os.environ.get("HUMANIZER_OPENAI_MODEL", "gpt-4o-mini")
CLOUD_REQUEST_TIMEOUT_SEC = float(os.environ.get("HUMANIZER_CLOUD_TIMEOUT_SEC", "120"))

_SUPPORTED_PROVIDERS = frozenset({"groq", "openai"})


class CloudAIError(Exception):
    """Cloud LLM provider failed or is misconfigured."""


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
    model = str(raw.get("model") or "").strip()
    if not model:
        model = DEFAULT_GROQ_MODEL if provider == "groq" else DEFAULT_OPENAI_MODEL
    return {
        "provider": provider,
        "api_key": api_key,
        "model": model,
    }


def _provider_url(provider: CloudProvider) -> str:
    if provider == "groq":
        return GROQ_API_URL
    return OPENAI_API_URL


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
    provider: CloudProvider,
    api_key: str,
    model: str,
    system: str,
    prompt: str,
    temperature: float,
    max_tokens: int,
) -> str:
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
            _provider_url(provider),
            headers=headers,
            json=payload,
            timeout=CLOUD_REQUEST_TIMEOUT_SEC,
        )
    except requests.RequestException as exc:
        raise CloudAIError(f"Could not reach {provider} API") from exc

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


def mask_api_key(api_key: str) -> str:
    key = api_key.strip()
    if len(key) <= 8:
        return "****"
    return f"{key[:4]}…{key[-4:]}"
