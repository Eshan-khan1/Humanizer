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
    apply_generate_hard_filters,
    build_generate_system_instruction,
    build_generate_user_message,
    build_rewrite_system_instruction,
    build_rewrite_user_message,
    finalize_generate_output,
    resolve_effective_generate_settings,
    _body_word_count,
    _count_email_body_paragraphs,
    _enforce_length_structure,
    _meets_generate_length_requirement,
    _parse_signoff_permanent_note,
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


class GenerateFidelityAndLengthTests(unittest.TestCase):
    def test_no_reason_rule_in_system(self) -> None:
        system = build_generate_system_instruction(
            "email",
            settings={"tonePreset": "friendly", "length": "long", "complexity": "simple"},
        )
        self.assertIn("NO REASON RULE", system)
        self.assertIn("NOT include any reason at all", system)
        self.assertIn("must NOT shorten the draft", system)
        self.assertIn("EXAMPLE — WITH REASON", system)
        self.assertIn("EXAMPLE — WITHOUT REASON", system)
        self.assertIn("clarifying what the user is asking for", system)
        self.assertIn("mentioning progress already made ONLY if the idea implies", system)
        self.assertIn("offering flexibility on timing", system)
        self.assertIn("asking what the reader needs next", system)
        self.assertNotIn("I am not adding a separate reason", system)
        self.assertNotIn("I am requesting an extension on the current deadline and would appreciate", system)

    def test_signoff_permanent_note_is_closing_only(self) -> None:
        name, remaining, only = _parse_signoff_permanent_note(
            "Always sign off with my name, Eshan."
        )
        self.assertTrue(only)
        self.assertEqual(name, "Eshan")
        self.assertEqual(remaining, "")

        settings = {
            "tonePreset": "friendly",
            "length": "medium",
            "complexity": "standard",
            "profile": {"permanentNote": "Always sign off with my name, Eshan."},
        }
        effective = resolve_effective_generate_settings(settings)
        self.assertTrue(effective["profile"].get("_signoff_note_only"))
        self.assertEqual(effective["profile"].get("fullName"), "Eshan")

        system = build_generate_system_instruction("email", settings=settings)
        self.assertIn("sign-off / signature only", system)
        self.assertIn("NEVER put this name in the greeting", system)

        draft = (
            "Subject: Extension\n\nHi Eshan,\n\nI need an extension.\n\nBest,\nSomeone\n"
        )
        out = apply_generate_hard_filters(
            draft, format_type="email", settings=settings, seed_baseline="extension"
        )
        out = finalize_generate_output(out, format_type="email", settings=settings)
        self.assertNotIn("Hi Eshan", out)
        self.assertIn("Eshan", out)
        self.assertRegex(out, r"(?m)^(Best|Thanks|Sincerely),?\s*$")

    def test_missing_name_uses_only_final_signature_placeholder(self) -> None:
        settings = {
            "tonePreset": "friendly",
            "length": "medium",
            "complexity": "standard",
            "profile": {},
        }
        system = build_generate_system_instruction("email", settings=settings)
        self.assertIn(
            '"[Your Name]" is the one and only bracketed placeholder allowed',
            system,
        )
        self.assertIn("Brackets must NEVER appear in the subject, greeting, or body", system)

        draft = (
            "Subject: Update\n\nHi there,\n\n"
            "I need an extension.\n\nBest,\n"
        )
        out = apply_generate_hard_filters(
            draft, format_type="email", settings=settings, seed_baseline="extension"
        )
        out = finalize_generate_output(
            out, format_type="email", settings=settings, seed_baseline="extension"
        )
        self.assertTrue(out.endswith("Best,\n[Your Name]"), out)
        self.assertEqual(out.count("[Your Name]"), 1)

    def test_long_guidance_examples_and_no_pad_boilerplate(self) -> None:
        system = build_generate_system_instruction(
            "email",
            settings={"tonePreset": "friendly", "length": "long", "complexity": "standard"},
        )
        length_rule = _rule_section(system, "RULE 2 — LENGTH")
        self.assertIn("EXAMPLE — WITH REASON", length_rule)
        self.assertIn("EXAMPLE — WITHOUT REASON", length_rule)
        self.assertIn("Would it be possible to have a few extra days", length_rule)
        self.assertNotIn("next Friday", length_rule)
        self.assertNotIn("following Monday", length_rule)
        # Only the two long examples — no old canned pad sentences in the length rule
        self.assertNotIn(
            "I am requesting an extension on the current deadline and would appreciate your approval",
            length_rule,
        )

        short_seed = (
            "Subject: Hello\n\nHi there,\n\nI need an extension.\n\nPlease help.\n\n"
            "Best,\nEshan\n"
        )
        idea = "asking my professor for a deadline extension"
        long = _enforce_length_structure(
            short_seed, format_type="email", length="long", seed_baseline=idea
        )
        lower = long.lower()
        # Enforcement must not inject paraphrased boilerplate pads
        self.assertNotIn("i am requesting an extension on the current deadline", lower)
        self.assertNotIn("a bit more time would let me finish the work carefully", lower)
        self.assertNotIn("i am not adding a separate reason", lower)

    def test_no_reason_filter_removes_unsupported_backstory_and_progress(self) -> None:
        settings = {
            "tonePreset": "friendly",
            "length": "long",
            "complexity": "standard",
            "profile": {},
        }
        draft = (
            "Subject: Extension Request\n\nHi Professor,\n\n"
            "I'm writing to request a deadline extension.\n\n"
            "I've been under additional responsibilities lately.\n\n"
            "My current progress includes outlining my approach and beginning research.\n\n"
            "I'm happy to share what I have so far.\n\n"
            "My situation has prevented me from reviewing my work thoroughly.\n\n"
            "Additional time would allow me to produce a higher-quality submission.\n\n"
            "Over the past few weeks, I've found myself juggling multiple projects "
            "and have fallen behind schedule.\n\n"
            "I know deadlines are important, but I want to ensure that my work "
            "meets the same high standards as usual.\n\n"
            "I'm glad to discuss any additional support or resources that would "
            "help me complete the assignment.\n\n"
            "Would it be possible to have until next Friday?\n\n"
            "I'm happy to work with whatever timeline is feasible. "
            "Please let me know what information you need next.\n\n"
            "Best,\n[Your Name]"
        )
        out = apply_generate_hard_filters(
            draft,
            format_type="email",
            settings=settings,
            seed_baseline="asking my professor for a deadline extension",
        )
        lower = out.lower()
        self.assertNotIn("additional responsibilities", lower)
        self.assertNotIn("current progress", lower)
        self.assertNotIn("outlining my approach", lower)
        self.assertNotIn("beginning research", lower)
        self.assertNotIn("what i have so far", lower)
        self.assertNotIn("my situation", lower)
        self.assertNotIn("higher-quality submission", lower)
        self.assertNotIn("juggling multiple projects", lower)
        self.assertNotIn("deadlines are important", lower)
        self.assertNotIn("additional support or resources", lower)
        self.assertNotIn("next friday", lower)
        self.assertIn("would it be possible to have a little more time", lower)
        self.assertIn("whatever timeline is feasible", lower)
        self.assertIn("information you need next", lower)
        self.assertGreaterEqual(_count_email_body_paragraphs(out), 5)


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
