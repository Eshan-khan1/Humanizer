"""Persistent Humanizer settings (local LLM model choices, etc.)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from macos.menubar.manager import OLLAMA_TAGS_URL, _http_json, support_dir

logger = logging.getLogger("humanizer.menubar")

DEFAULT_GRAMMAR_MODEL = "humanizer-grammar"
DEFAULT_WRITING_MODEL = "humanizer-writing"


def settings_path() -> Path:
    return support_dir() / "settings.json"


def load_settings() -> dict[str, Any]:
    path = settings_path()
    data: dict[str, Any] = {
        "grammar_model": DEFAULT_GRAMMAR_MODEL,
        "writing_model": DEFAULT_WRITING_MODEL,
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
    except (OSError, json.JSONDecodeError, TypeError) as exc:
        logger.warning("Could not read settings: %s", exc)
    return data


def save_settings(
    *,
    grammar_model: str | None = None,
    writing_model: str | None = None,
) -> dict[str, Any]:
    data = load_settings()
    if grammar_model is not None and grammar_model.strip():
        data["grammar_model"] = grammar_model.strip()
    if writing_model is not None and writing_model.strip():
        data["writing_model"] = writing_model.strip()
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return data


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
        models.append(
            {
                "name": name.strip(),
                "size": entry.get("size"),
                "modified_at": entry.get("modified_at"),
                "digest": entry.get("digest"),
            }
        )
    models.sort(key=lambda m: m["name"].lower())
    return models


def apply_to_env(env: dict[str, str]) -> dict[str, str]:
    """Inject selected local LLM models into a server process environment."""
    data = load_settings()
    env["OLLAMA_GRAMMAR_MODEL"] = str(data.get("grammar_model") or DEFAULT_GRAMMAR_MODEL)
    env["OLLAMA_WRITING_MODEL"] = str(data.get("writing_model") or DEFAULT_WRITING_MODEL)
    # Keep legacy alias in sync for older code paths.
    env["OLLAMA_MODEL"] = env["OLLAMA_GRAMMAR_MODEL"]
    return env
