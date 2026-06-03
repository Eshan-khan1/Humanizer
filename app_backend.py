"""Backend API for Humanize — exposed to the web UI via PyWebView."""

from __future__ import annotations

from typing import Any

from humanizer import (
    calculate_ai_score,
    count_pipeline_edits,
    humanize,
    is_ollama_running,
)

WORD_LIMIT = 1200
VALID_INTENSITIES = frozenset({"mild", "moderate", "aggressive"})


class HumanizeAPI:
    """Python bridge for the HTML frontend (PyWebView js_api)."""

    def get_config(self) -> dict[str, Any]:
        return {
            "word_limit": WORD_LIMIT,
            "intensities": ["mild", "moderate", "aggressive"],
            "default_intensity": "moderate",
            "ollama_available": is_ollama_running(),
        }

    def humanize_text(self, text: str, intensity: str = "moderate") -> dict[str, Any]:
        """
        Humanize input text and return scores and change count.

        Returns:
            dict with keys: ok, result, score_before, score_after, changes, error
        """
        text = (text or "").strip()
        intensity = (intensity or "moderate").lower()

        if not text:
            return {
                "ok": False,
                "error": "Enter text in the Input Text area.",
            }

        if intensity not in VALID_INTENSITIES:
            return {
                "ok": False,
                "error": f"Invalid intensity: {intensity}",
            }

        words = text.split()
        if len(words) > WORD_LIMIT:
            text = " ".join(words[:WORD_LIMIT])

        try:
            score_before = calculate_ai_score(text)
            result = humanize(text, intensity=intensity)  # type: ignore[arg-type]
            score_after = calculate_ai_score(result)
            changes = count_pipeline_edits(text, intensity)  # type: ignore[arg-type]
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

        return {
            "ok": True,
            "result": result,
            "score_before": score_before,
            "score_after": score_after,
            "changes": changes,
        }
