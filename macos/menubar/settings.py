"""Persistent Humanizer settings (local LLM model choices, cloud API key, etc.)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from macos.menubar.manager import OLLAMA_TAGS_URL, _http_json, support_dir

logger = logging.getLogger("humanizer.menubar")

DEFAULT_GRAMMAR_MODEL = "humanizer-grammar"
DEFAULT_WRITING_MODEL = "humanizer-writing"
DEFAULT_AI_PROVIDER = "local"

# Friendly labels in the Mac app Settings → Local LLM pickers.
# Keys may be bare names or full Ollama tags (name:tag).
MODEL_LABELS: dict[str, str] = {
    "humanizer-writing": "Qwen 7B / trained",
    "qwen-7b-trained": "Qwen 7B / trained",
    "humanizer-grammar": "Qwen grammar / trained",
    "qwen2.5:7b": "Qwen 7B",
    "qwen2.5:3b-instruct": "Qwen 3B",
    "qwen2.5:0.5b": "Qwen 0.5B",
    "qwen3:8b": "Qwen 3 8B",
}


def model_label(name: str) -> str:
    """Human-readable label for an Ollama model name."""
    raw = (name or "").strip()
    if not raw:
        return raw
    if raw in MODEL_LABELS:
        return MODEL_LABELS[raw]
    base = raw.split(":", 1)[0]
    return MODEL_LABELS.get(base, raw)


def settings_path() -> Path:
    return support_dir() / "settings.json"


def _normalize_ai_provider(value: Any) -> str:
    provider = str(value or DEFAULT_AI_PROVIDER).strip().lower()
    if provider in {"", "local", "ollama"}:
        return "local"
    if provider in {"api", "groq", "openai"}:
        return provider
    return "local"


def load_settings() -> dict[str, Any]:
    path = settings_path()
    data: dict[str, Any] = {
        "grammar_model": DEFAULT_GRAMMAR_MODEL,
        "writing_model": DEFAULT_WRITING_MODEL,
        "ai_provider": DEFAULT_AI_PROVIDER,
        "ai_api_key": "",
        "ai_base_url": "",
        "ai_model": "",
        "feature_grammar": True,
        "feature_rewrite": True,
        "feature_generate": True,
    }
    if not path.is_file():
        return data
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            if isinstance(raw.get("grammar_model"), str) and raw["grammar_model"].strip():
                data["grammar_model"] = raw["grammar_model"].strip()
            if isinstance(raw.get("writing_model"), str) and raw["writing_model"].strip():
                data["writing_model"] = raw["writing_model"].strip()
            data["ai_provider"] = _normalize_ai_provider(raw.get("ai_provider"))
            if isinstance(raw.get("ai_api_key"), str):
                data["ai_api_key"] = raw["ai_api_key"].strip()
            if isinstance(raw.get("ai_base_url"), str):
                data["ai_base_url"] = raw["ai_base_url"].strip()
            if isinstance(raw.get("ai_model"), str):
                data["ai_model"] = raw["ai_model"].strip()
            for key in ("feature_grammar", "feature_rewrite", "feature_generate"):
                if key in raw:
                    data[key] = bool(raw[key])
    except (OSError, json.JSONDecodeError, TypeError) as exc:
        logger.warning("Could not read settings: %s", exc)
    return data


def save_settings(
    *,
    grammar_model: str | None = None,
    writing_model: str | None = None,
    ai_provider: str | None = None,
    ai_api_key: str | None = None,
    ai_base_url: str | None = None,
    ai_model: str | None = None,
    feature_grammar: bool | None = None,
    feature_rewrite: bool | None = None,
    feature_generate: bool | None = None,
) -> dict[str, Any]:
    data = load_settings()
    if grammar_model is not None and grammar_model.strip():
        data["grammar_model"] = grammar_model.strip()
    if writing_model is not None and writing_model.strip():
        data["writing_model"] = writing_model.strip()
    if ai_provider is not None:
        data["ai_provider"] = _normalize_ai_provider(ai_provider)
    if ai_api_key is not None:
        data["ai_api_key"] = ai_api_key.strip()
    if ai_base_url is not None:
        data["ai_base_url"] = ai_base_url.strip()
    if ai_model is not None:
        data["ai_model"] = ai_model.strip()
    if feature_grammar is not None:
        data["feature_grammar"] = bool(feature_grammar)
    if feature_rewrite is not None:
        data["feature_rewrite"] = bool(feature_rewrite)
    if feature_generate is not None:
        data["feature_generate"] = bool(feature_generate)
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return data


def features_summary() -> dict[str, bool]:
    data = load_settings()
    return {
        "feature_grammar": bool(data.get("feature_grammar", True)),
        "feature_rewrite": bool(data.get("feature_rewrite", True)),
        "feature_generate": bool(data.get("feature_generate", True)),
    }


def feature_enabled(name: str) -> bool:
    """name: grammar | rewrite | generate"""
    key = f"feature_{str(name or '').strip().lower()}"
    return bool(features_summary().get(key, True))


def cloud_ai_config() -> dict[str, Any] | None:
    """Return a request-shaped AI config from app Settings, or None for local."""
    data = load_settings()
    provider = _normalize_ai_provider(data.get("ai_provider"))
    if provider == "local":
        return None
    api_key = str(data.get("ai_api_key") or "").strip()
    if not api_key:
        return None
    cfg: dict[str, Any] = {"provider": provider, "api_key": api_key}
    base_url = str(data.get("ai_base_url") or "").strip()
    model = str(data.get("ai_model") or "").strip()
    if base_url:
        cfg["base_url"] = base_url
    if model:
        cfg["model"] = model
    return cfg


def ai_status_summary() -> dict[str, Any]:
    """Safe status fields (never include the raw API key)."""
    data = load_settings()
    provider = _normalize_ai_provider(data.get("ai_provider"))
    has_key = bool(str(data.get("ai_api_key") or "").strip())
    return {
        "ai_provider": provider,
        "ai_configured": provider != "local" and has_key,
        "ai_has_key": has_key,
        "ai_base_url": str(data.get("ai_base_url") or "").strip(),
        "ai_model": str(data.get("ai_model") or "").strip(),
    }


def list_ollama_models() -> list[dict[str, Any]]:
    payload = _http_json(OLLAMA_TAGS_URL, timeout=3.0)
    if not payload or not isinstance(payload.get("models"), list):
        return []
    models: list[dict[str, Any]] = []
    for entry in payload["models"]:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name") or entry.get("model")
        if not isinstance(name, str) or not name.strip():
            continue
        cleaned = name.strip()
        models.append(
            {
                "name": cleaned,
                "label": model_label(cleaned),
                "size": entry.get("size"),
                "modified_at": entry.get("modified_at"),
                "digest": entry.get("digest"),
            }
        )
    models.sort(key=lambda m: str(m["label"]).lower())
    return models


def apply_to_env(env: dict[str, str]) -> dict[str, str]:
    """Inject selected local LLM models into a server process environment."""
    data = load_settings()
    env["OLLAMA_GRAMMAR_MODEL"] = str(data.get("grammar_model") or DEFAULT_GRAMMAR_MODEL)
    env["OLLAMA_WRITING_MODEL"] = str(data.get("writing_model") or DEFAULT_WRITING_MODEL)
    # Keep legacy alias in sync for older code paths.
    env["OLLAMA_MODEL"] = env["OLLAMA_GRAMMAR_MODEL"]
    return env
