#!/usr/bin/env python3
"""Unit tests: Generate/Rewrite system instructions keep settings independent."""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from writing_agent import (  # noqa: E402
    GENERATE_COMPLEXITY_GUIDANCE,
    GENERATE_LENGTH_GUIDANCE,
    TONE_PRESET_GUIDANCE,
    build_generate_system_instruction,
    build_generate_user_message,
    build_rewrite_system_instruction,
    build_rewrite_user_message,
)


def _rule_section(system: str, rule_prefix: str) -> str:
    """Extract text from RULE N — … until the next RULE or end."""
    pattern = re.compile(
        rf"({re.escape(rule_prefix)}.*?)(?=\nRULE \d+ —|\nFORMAT RULES:|\nOUTPUT:|\Z)",
        re.DOTALL,
    )
    match = pattern.search(system)
    return match.group(1) if match else ""


class GeneratePromptIndependenceTests(unittest.TestCase):
    def test_user_message_is_only_seed(self) -> None:
        seed = "Ask for a one-week deadline extension"
        user = build_generate_user_message(seed)
        self.assertEqual(user, seed)
        self.assertNotIn("RULE", user)
        self.assertNotIn("TONE", user)
        self.assertNotIn("LENGTH", user)

    def test_system_has_separate_rules_including_profile_and_note(self) -> None:
        system = build_generate_system_instruction(
            "email",
            notes="",
            settings={
                "tonePreset": "formal",
                "length": "short",
                "complexity": "simple",
                "profile": {
                    "fullName": "Eshan Khan",
                    "permanentNote": "Always mention I am a TA",
                },
            },
        )
        self.assertIn("SEPARATE AND INDEPENDENT RULES", system)
        self.assertIn("RULE 1 — TONE", system)
        self.assertIn("RULE 2 — LENGTH", system)
        self.assertIn("RULE 3 — VOCABULARY", system)
        self.assertIn("RULE 4 — PERSONAL INFO", system)
        self.assertIn("RULE 5 — PERMANENT NOTE", system)
        self.assertIn("MEANING & FIDELITY", system)
        self.assertIn("Eshan Khan", system)
        self.assertIn("Always mention I am a TA", system)
        self.assertIn("Do not change the meaning", system)
        self.assertIn("Do not invent facts", system)
        self.assertIn("Do not add new information beyond what the user implied", system)

    def test_tone_change_does_not_alter_length_or_vocabulary_rules(self) -> None:
        base = {
            "length": "medium",
            "complexity": "standard",
            "profile": {"fullName": "Alex"},
        }
        formal = build_generate_system_instruction(
            "email", settings={**base, "tonePreset": "formal"}
        )
        casual = build_generate_system_instruction(
            "email", settings={**base, "tonePreset": "casual"}
        )
        formal_len = _rule_section(formal, "RULE 2 — LENGTH")
        casual_len = _rule_section(casual, "RULE 2 — LENGTH")
        formal_vocab = _rule_section(formal, "RULE 3 — VOCABULARY")
        casual_vocab = _rule_section(casual, "RULE 3 — VOCABULARY")

        self.assertEqual(formal_len, casual_len)
        self.assertEqual(formal_vocab, casual_vocab)
        self.assertIn(GENERATE_LENGTH_GUIDANCE["medium"].split("\n", 1)[0], formal_len)
        self.assertNotEqual(
            _rule_section(formal, "RULE 1 — TONE"),
            _rule_section(casual, "RULE 1 — TONE"),
        )
        self.assertIn("formal", _rule_section(formal, "RULE 1 — TONE").lower())
        self.assertIn("casual", _rule_section(casual, "RULE 1 — TONE").lower())

    def test_length_change_does_not_alter_tone_or_vocabulary_rules(self) -> None:
        base = {"tonePreset": "friendly", "complexity": "advanced"}
        short = build_generate_system_instruction(
            "email", settings={**base, "length": "short"}
        )
        long = build_generate_system_instruction(
            "email", settings={**base, "length": "long"}
        )
        self.assertEqual(
            _rule_section(short, "RULE 1 — TONE"),
            _rule_section(long, "RULE 1 — TONE"),
        )
        self.assertEqual(
            _rule_section(short, "RULE 3 — VOCABULARY"),
            _rule_section(long, "RULE 3 — VOCABULARY"),
        )
        self.assertNotEqual(
            _rule_section(short, "RULE 2 — LENGTH"),
            _rule_section(long, "RULE 2 — LENGTH"),
        )

    def test_vocabulary_change_does_not_alter_tone_or_length_rules(self) -> None:
        base = {"tonePreset": "formal", "length": "long"}
        simple = build_generate_system_instruction(
            "email", settings={**base, "complexity": "simple"}
        )
        advanced = build_generate_system_instruction(
            "email", settings={**base, "complexity": "advanced"}
        )
        self.assertEqual(
            _rule_section(simple, "RULE 1 — TONE"),
            _rule_section(advanced, "RULE 1 — TONE"),
        )
        self.assertEqual(
            _rule_section(simple, "RULE 2 — LENGTH"),
            _rule_section(advanced, "RULE 2 — LENGTH"),
        )
        self.assertNotEqual(
            _rule_section(simple, "RULE 3 — VOCABULARY"),
            _rule_section(advanced, "RULE 3 — VOCABULARY"),
        )
        self.assertIn(
            GENERATE_COMPLEXITY_GUIDANCE["simple"].split("\n", 1)[0],
            _rule_section(simple, "RULE 3 — VOCABULARY"),
        )

    def test_all_presets_visible_in_system(self) -> None:
        for tone in TONE_PRESET_GUIDANCE:
            for length in GENERATE_LENGTH_GUIDANCE:
                for complexity in GENERATE_COMPLEXITY_GUIDANCE:
                    system = build_generate_system_instruction(
                        "essay",
                        settings={
                            "tonePreset": tone,
                            "length": length,
                            "complexity": complexity,
                        },
                    )
                    self.assertIn("RULE 1 — TONE", system)
                    self.assertIn("RULE 2 — LENGTH", system)
                    self.assertIn("RULE 3 — VOCABULARY", system)
                    # Spot-check that guidance fragments appear
                    self.assertIn(
                        GENERATE_LENGTH_GUIDANCE[length].splitlines()[0][:40],
                        system,
                    )


class RewritePromptIndependenceTests(unittest.TestCase):
    def test_user_message_is_only_selected_text(self) -> None:
        selected = "Please submit the form by Friday."
        user = build_rewrite_user_message(selected)
        self.assertEqual(user, selected)
        self.assertNotIn("RULE", user)
        self.assertNotIn("REWRITE RULES", user)

    def test_system_has_independent_rules_and_meaning(self) -> None:
        system = build_rewrite_system_instruction(
            "Rewrite in a casual, natural tone.",
            direct=True,
        )
        self.assertIn("SEPARATE AND INDEPENDENT RULES", system)
        self.assertIn("RULE 1 — TONE", system)
        self.assertIn("RULE 2 — LENGTH", system)
        self.assertIn("RULE 3 — VOCABULARY", system)
        self.assertIn("REWRITE RULES", system)
        self.assertIn("casual", system.lower())
        self.assertIn("Do not invent facts", system)
        self.assertIn("EXAMPLE (casual)", system)

    def test_tone_instruction_change_keeps_length_and_vocab_rule_headers(self) -> None:
        formal = build_rewrite_system_instruction(
            "Rewrite in a professional, formal tone.", direct=True
        )
        friendly = build_rewrite_system_instruction(
            "Rewrite in a warm and friendly tone.", direct=True
        )
        formal_len = _rule_section(formal, "RULE 2 — LENGTH")
        friendly_len = _rule_section(friendly, "RULE 2 — LENGTH")
        # Length and vocab policy text for rewrite is fixed (keep same length)
        self.assertEqual(formal_len, friendly_len)
        self.assertNotEqual(
            _rule_section(formal, "RULE 1 — TONE"),
            _rule_section(friendly, "RULE 1 — TONE"),
        )


if __name__ == "__main__":
    unittest.main()
