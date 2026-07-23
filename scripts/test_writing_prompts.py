#!/usr/bin/env python3
"""Unit tests: Generate/Rewrite system instructions keep settings independent."""

from __future__ import annotations

from difflib import SequenceMatcher
import re
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from writing_agent import (  # noqa: E402
    GENERATE_COMPLEXITY_GUIDANCE,
    GENERATE_LENGTH_GUIDANCE,
    TONE_PRESET_GUIDANCE,
    WritingAgent,
    apply_generate_hard_filters,
    build_generate_system_instruction,
    build_generate_user_message,
    build_rewrite_system_instruction,
    build_rewrite_user_message,
    finalize_generate_output,
    resolve_effective_generate_settings,
    _apply_advanced_complexity_replacements,
    _apply_blunt_tone_voice,
    _apply_simple_complexity_replacements,
    _body_word_count,
    _count_body_sentences,
    _count_email_body_paragraphs,
    _canonicalize_generated_email,
    _clean_generate_typography,
    _dedupe_generic_request_sentences,
    _dedupe_semantic_requests,
    _enforce_length_structure,
    _ensure_seed_list_format,
    _fact_is_reflected,
    _format_inline_lists,
    _generate_candidate_score,
    _generate_candidate_rejection_reasons,
    _generate_length_bounds,
    _inject_informational_content,
    _meets_generate_length_requirement,
    _ensure_seed_role_mentions,
    _normalize_unseeded_timing_details,
    _parse_email_sections,
    _parse_generation_note,
    _permanent_note_sentence,
    _seed_list_plan,
    _seed_states_a_reason,
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
        self.assertIn("selected Length range", system)
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
        self.assertIn("Would it be possible to grant an extension", length_rule)
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
            "Unexpected family commitments have made it difficult for me to complete the work.\n\n"
            "The sink in my apartment is dripping steadily and causing water damage.\n\n"
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
        self.assertNotIn("family commitments", lower)
        self.assertNotIn("my apartment", lower)
        self.assertNotIn("next friday", lower)
        self.assertIn("request a deadline extension", lower)
        self.assertIn("deadline extension", lower)
        self.assertNotIn("standard process for this request", lower)
        self.assertNotIn("information you need from me", lower)
        self.assertGreaterEqual(_count_email_body_paragraphs(out), 5)

    def test_length_bounds_and_candidate_scoring_use_filtered_output(self) -> None:
        seed = "asking my professor for a deadline extension"
        self.assertEqual(_generate_length_bounds("medium", seed), (35, 80))
        self.assertEqual(
            _generate_length_bounds(
                "medium",
                "Ask the team for a detailed project update covering completed milestones, "
                "current blockers, named owners, business impacts, open decisions, "
                "recommendations, upcoming priorities, supporting context, and the agenda "
                "for Thursday's planning meeting.",
            ),
            (65, 160),
        )
        self.assertEqual(_generate_length_bounds("long", seed), (55, 100))

        short = (
            "Subject: Extension\n\nHi there,\n\nI need an extension.\n\nBest,\n[Your Name]"
        )
        body = " ".join(["Please consider my request."] * 24)
        valid = (
            f"Subject: Extension\n\nHi there,\n\n{body[:len(body)//2]}\n\n"
            f"{body[len(body)//2:]}\n\nBest,\n[Your Name]"
        )
        self.assertFalse(
            _meets_generate_length_requirement(short, "email", "medium", seed)
        )
        self.assertGreater(
            _generate_candidate_score(
                valid, format_type="email", length="medium", seed_baseline=seed
            ),
            _generate_candidate_score(
                short, format_type="email", length="medium", seed_baseline=seed
            ),
        )

    def test_sparse_ideas_get_distinct_topic_specific_bodies(self) -> None:
        settings = {
            "tonePreset": "friendly",
            "length": "long",
            "complexity": "standard",
            "profile": {},
        }
        extension_draft = (
            "Subject: Request\n\nHi there,\n\n"
            "I am writing to request a deadline extension.\n\nBest,"
        )
        sink_draft = (
            "Subject: Request\n\nHi there,\n\n"
            "The sink is leaking, and I need someone this week.\n\nBest,"
        )
        extension = apply_generate_hard_filters(
            extension_draft,
            format_type="email",
            settings=settings,
            seed_baseline="asking my professor for a deadline extension",
        )
        sink = apply_generate_hard_filters(
            sink_draft,
            format_type="email",
            settings=settings,
            seed_baseline="tell my landlord the sink is leaking, need someone this week",
        )
        extension_body = _parse_email_sections(extension)["body"].lower()
        sink_body = _parse_email_sections(sink)["body"].lower()
        self.assertIn("deadline extension", extension_body)
        self.assertIn("sink is leaking", sink_body)
        self.assertLess(
            SequenceMatcher(None, extension_body, sink_body).ratio(),
            0.55,
        )
        for body in (extension_body, sink_body):
            self.assertNotIn("standard process for this request", body)
            self.assertNotIn("conditions or requirements attached to the request", body)

    def test_repeated_let_me_know_and_process_sentences_are_deduplicated(self) -> None:
        draft = (
            "Subject: Request\n\nHi there,\n\n"
            "Please let me know whether this works. Let me know what you decide.\n\n"
            "I will follow the normal process. Tell me about the standard process.\n\n"
            "Best,"
        )
        out = _dedupe_generic_request_sentences(draft, "email").lower()
        self.assertEqual(out.count("let me know"), 1)
        self.assertEqual(len(re.findall(r"\bprocess\b", out)), 1)

    def test_complexity_examples_produce_clearly_different_wording(self) -> None:
        standard = (
            "I need the report by Monday, or the project timeline will be affected. "
            "Could you share the current status of the contract? "
            "Please let me know if there's anything you need from me."
        )
        simple = _apply_simple_complexity_replacements(standard)
        advanced = _apply_advanced_complexity_replacements(standard)
        self.assertIn("we'll be late", simple)
        self.assertIn("send me an update on the contract", simple)
        self.assertIn("avoid any disruption to the project timeline", advanced)
        self.assertIn("where things currently stand with the contract", advanced)
        self.assertIn("anything further you require from me", advanced)
        self.assertGreater(len(advanced.split()), len(simple.split()))

    def test_permanent_tone_note_is_applied_not_injected(self) -> None:
        effective = resolve_effective_generate_settings(
            {
                "tonePreset": "casual",
                "length": "short",
                "complexity": "standard",
                "profile": {"permanentNote": "Make it more formal than usual."},
            }
        )
        self.assertEqual(effective["tone_preset"], "formal")
        self.assertEqual(effective["profile"]["permanentNote"], "")
        self.assertEqual(effective["profile"]["_permanent_note_raw"], "")

    def test_permanent_style_note_is_instruction_not_fact(self) -> None:
        style = _parse_generation_note(
            "Always keep emails to my landlord blunt and to the point."
        )
        self.assertTrue(style["has_tone_instruction"])
        self.assertEqual(style["tone_preset_override"], "blunt")
        self.assertIsNone(style["informational_content"])

        fact = _parse_generation_note("My referral number is REF-88291.")
        self.assertFalse(fact["has_tone_instruction"])
        self.assertEqual(
            fact["informational_content"], "My referral number is REF-88291."
        )

        effective = resolve_effective_generate_settings(
            {
                "tonePreset": "friendly",
                "profile": {
                    "permanentNote": (
                        "Always keep emails to my landlord blunt and to the point."
                    )
                },
            }
        )
        self.assertEqual(effective["tone_preset"], "blunt")
        self.assertIn("blunt", effective["profile"].get("_style_instruction", "").lower())

        blunted = _apply_blunt_tone_voice(
            "Subject: Heater\n\nDear Sir or Madam,\n\n"
            "I am writing to request that the broken heater be repaired at your earliest convenience.\n\n"
            "I would greatly appreciate a prompt resolution of this issue.\n\n"
            "Sincerely,\n[Your Name]"
        )
        self.assertNotRegex(blunted.lower(), r"greatly appreciate|would it be possible|i hope")
        self.assertIn("heater", blunted.lower())
        self.assertRegex(blunted.lower(), r"\b(?:fix|repair|repaired)\b")

    def test_full_name_signoff_note_stays_in_signature(self) -> None:
        name, remaining, signoff_only = _parse_signoff_permanent_note(
            "Sign off with my full name, Marcus Webb."
        )
        self.assertEqual(name, "Marcus Webb")
        self.assertEqual(remaining, "")
        self.assertTrue(signoff_only)

        effective = resolve_effective_generate_settings(
            {
                "tonePreset": "friendly",
                "profile": {
                    "permanentNote": "Sign off with my full name, Marcus Webb."
                },
            }
        )
        output = _canonicalize_generated_email(
            "Subject: Update\n\nHi Marcus Webb,\n\n"
            "Full name, Marcus Webb. Here is the requested update.\n\n"
            "Best,\n[Your Name]",
            tone_preset="friendly",
            profile=effective["profile"],
            seed_baseline="Here is the requested update.",
        )
        self.assertEqual(output.count("Marcus Webb"), 1)
        self.assertTrue(output.endswith("Best,\nMarcus Webb"))
        self.assertNotIn("Hi Marcus Webb", output)

    def test_permanent_date_fact_recognizes_paraphrase(self) -> None:
        self.assertTrue(
            _fact_is_reflected(
                "My current lease ends August 31st.",
                "The lease expires on August 31st.",
            )
        )

    def test_unseeded_date_components_are_removed(self) -> None:
        seed = "My claim #48213 was filed June 3rd."
        output = _normalize_unseeded_timing_details(
            "Claim #48213 was filed June 3, 2023.", seed
        )
        self.assertIn("#48213", output)
        self.assertIn("June 3", output)
        self.assertNotIn("2023", output)
        elapsed = _normalize_unseeded_timing_details(
            "As this has been over a month since filing, please provide an update.",
            f"{seed} It has not been processed.",
        )
        self.assertNotIn("over a month", elapsed)
        self.assertIn("claim has not yet been processed", elapsed)

        month_only = _normalize_unseeded_timing_details(
            "The review is scheduled for June 14th.", "The review is in June."
        )
        self.assertIn("June", month_only)
        self.assertNotIn("14", month_only)

    def test_invalid_raw_seed_candidate_is_rejected(self) -> None:
        source = "Ask my accountant for an update on my tax filing."
        candidate = (
            "Subject: Tax Filing\n\nHi there,\n\n"
            f"{source}\n\nBest,\n[Your Name]"
        )
        reasons = _generate_candidate_rejection_reasons(
            candidate,
            format_type="email",
            length="medium",
            seed_baseline=source,
            source_text=source,
        )
        self.assertIn("raw_source_leak", reasons)
        self.assertTrue(
            any(reason.startswith("length_or_structure") for reason in reasons)
        )

    def test_complete_medium_draft_accepts_small_word_count_shortfall(self) -> None:
        seed = "Ask my accountant for an update on my tax filing."
        candidate = (
            "Subject: Tax Filing Update\n\nHi there,\n\n"
            "Could you please share the current status of my tax filing and confirm "
            "whether anything remains outstanding?\n\n"
            "Please also tell me if you need any additional tax documents from me.\n\n"
            "Best,\nPriya"
        )
        self.assertEqual(_body_word_count(candidate, "email"), 30)
        self.assertTrue(
            _meets_generate_length_requirement(
                candidate, "email", "medium", seed
            )
        )

    def test_complete_sparse_long_draft_accepts_four_paragraphs(self) -> None:
        seed = "ask neighbor to trim the hedge"
        candidate = (
            "Subject: Hedge Trimming\n\nHi there,\n\n"
            "Could you please trim the hedge along our shared boundary?\n\n"
            "It has grown enough that trimming it would keep the hedge manageable.\n\n"
            "Please choose a time that works for you and handle the trimming when convenient.\n\n"
            "Let me know once the hedge has been trimmed.\n\nBest,\n[Your Name]"
        )
        self.assertEqual(_count_email_body_paragraphs(candidate), 4)
        self.assertTrue(
            _meets_generate_length_requirement(
                candidate, "email", "long", seed
            )
        )

    def test_seed_lists_are_forced_onto_separate_lines(self) -> None:
        vendor_seed = (
            "Ask the vendor for a revised quote that separates hardware costs, "
            "installation labor, and the annual maintenance contract, and ask them "
            "to flag any items with long lead times so we can plan the rollout schedule."
        )
        intern_seed = (
            "Ask the new intern to set up their laptop with the VPN, get added to the "
            "team Slack channel, complete the security training module, and schedule "
            "a 1:1 with their onboarding buddy, all before Friday."
        )
        self.assertEqual(len(_seed_list_plan(vendor_seed)[1]), 3)
        self.assertEqual(len(_seed_list_plan(intern_seed)[1]), 4)

        vendor = _ensure_seed_list_format(
            "Subject: Quote\n\nDear Sir or Madam,\n\n"
            "Please separate hardware costs, installation labor, and maintenance "
            "in the revised quote. Please flag long lead times.\n\nSincerely,\n[Your Name]",
            format_type="email",
            seed_baseline=vendor_seed,
        )
        intern = _ensure_seed_list_format(
            "Subject: Onboarding\n\nDear Sir or Madam,\n\n"
            "Set up the VPN. Also join Slack. Complete security training, and "
            "schedule the buddy meeting before Friday.\n\nSincerely,\n[Your Name]",
            format_type="email",
            seed_baseline=intern_seed,
        )
        self.assertEqual(len(re.findall(r"(?m)^- ", vendor)), 3)
        self.assertEqual(len(re.findall(r"(?m)^- ", intern)), 4)

        filtered_vendor = apply_generate_hard_filters(
            "Subject: Quote\n\nDear Sir or Madam,\n\n"
            "Please provide a revised quote separating hardware, installation, "
            "and maintenance costs.\n\nPlease flag long lead times.\n\n"
            "Sincerely,\n[Your Name]",
            format_type="email",
            settings={
                "tonePreset": "formal",
                "length": "medium",
                "complexity": "standard",
            },
            seed_baseline=vendor_seed,
        )
        self.assertNotIn("current status of the contract", filtered_vendor.lower())
        self.assertNotIn("contract items that still need", filtered_vendor.lower())

    def test_generate_errors_after_three_invalid_candidates(self) -> None:
        source = "Ask my accountant for an update on my tax filing."
        raw = (
            "Subject: Tax Filing\n\nHi there,\n\n"
            f"{source}\n\nBest,\n[Your Name]"
        )
        with patch("writing_agent._call_llm", return_value=raw) as call:
            with self.assertRaisesRegex(
                RuntimeError, "could not produce a complete draft"
            ):
                WritingAgent().generate(
                    source,
                    "email",
                    settings={
                        "tonePreset": "friendly",
                        "length": "medium",
                        "complexity": "standard",
                    },
                )
        self.assertEqual(call.call_count, 3)

    def test_semantic_duplicate_requests_collapse(self) -> None:
        draft = (
            "Subject: Contract\n\nHi there,\n\n"
            "Could you share the current status of the contract? "
            "Can you send me an update on the contract?\n\n"
            "I am writing to request a deadline extension. "
            "Please confirm whether the deadline extension can be granted.\n\n"
            "Please submit your project updates before the meeting. "
            "Please include every team update before the meeting.\n\n"
            "Let me know if any updates will not be ready before the meeting. "
            "If an update will not be ready before the meeting, identify which one is outstanding.\n\n"
            "Best,"
        )
        out = _dedupe_semantic_requests(draft, "email").lower()
        self.assertEqual(out.count("contract?"), 1)
        self.assertEqual(out.count("deadline extension"), 1)
        self.assertIn("submit your project updates", out)
        self.assertNotIn("include every team update", out)
        self.assertEqual(out.count("not be ready before the meeting"), 1)

    def test_inline_lists_are_split_without_changing_regular_prose(self) -> None:
        numbered = _format_inline_lists(
            "Each update should cover: 1. Completed milestones. "
            "2. Current blockers and impact. 3. Leadership decisions. "
            "4. Priorities for next week. These updates will shape the agenda."
        )
        self.assertRegex(numbered, r"(?m)^1\. Completed milestones\.$")
        self.assertRegex(numbered, r"(?m)^4\. Priorities for next week\.$")
        self.assertNotIn("1. Completed milestones. 2.", numbered)
        self.assertIn("\n\nThese updates will shape the agenda.", numbered)

        bulleted = _format_inline_lists(
            "Please cover: - milestones - blockers - decisions - priorities"
        )
        self.assertEqual(
            len(re.findall(r"(?m)^- ", bulleted)),
            4,
        )
        leading_bullets = _format_inline_lists(
            "- milestones - blockers - decisions - priorities"
        )
        self.assertEqual(len(re.findall(r"(?m)^- ", leading_bullets)), 4)

        natural = _format_inline_lists(
            "Each update should cover completed milestones, current blockers with "
            "their owners and impact, decisions needing leadership review with options "
            "and a recommendation, and priorities for next week. The updates are due Wednesday."
        )
        self.assertEqual(len(re.findall(r"(?m)^- ", natural)), 4)
        self.assertRegex(natural, r"(?m)^- Current blockers with their owners and impact$")
        self.assertIn("\n\nThe updates are due Wednesday.", natural)

        existing = _format_inline_lists(
            "- Priorities for next week. These updates will shape the agenda."
        )
        self.assertEqual(
            existing,
            "- Priorities for next week.\n\nThese updates will shape the agenda.",
        )
        self.assertEqual(
            _format_inline_lists("1. Completed milestones. 2."),
            "1. Completed milestones.",
        )

        prose = "The update covers milestones, blockers, and decisions in one sentence."
        self.assertEqual(_format_inline_lists(prose), prose)

    def test_unseeded_timing_cleanup_handles_observed_variants(self) -> None:
        seed = "asking my professor for a deadline extension"
        text = (
            "The assignment is due tomorrow. Could you extend the due date by a week or two? "
            "Could I have a few extra days? The assignment is due soon, October 14th. "
            "Could you grant me an additional week or two? "
            "Could you extend the deadline by one additional day?"
        )
        cleaned = _normalize_unseeded_timing_details(text, seed).lower()
        self.assertNotIn("tomorrow", cleaned)
        self.assertNotIn("week or two", cleaned)
        self.assertNotIn("few extra days", cleaned)
        self.assertNotIn("october 14th", cleaned)
        self.assertNotIn("due soon", cleaned)
        self.assertNotIn("additional week or two", cleaned)
        self.assertNotIn("one additional day", cleaned)
        self.assertNotRegex(cleaned, r"\b(?:by|on|until|for)\s+[?.!,]")

        grounded = _normalize_unseeded_timing_details(
            "Please send someone today or tomorrow.",
            "the sink is leaking, need someone this week",
        ).lower()
        self.assertNotIn("today", grounded)
        self.assertNotIn("tomorrow", grounded)
        self.assertIn("this week", grounded)

    def test_email_canonicalizer_is_idempotent(self) -> None:
        raw = (
            "Subject: Update\n\nHi Eshan,\n\nI wanted to ask an extension .\n\n"
            "Thankfully,\n\nBest,\nSomeone\n\nSincerely,\n[Your Name]"
        )
        profile = {"fullName": "Eshan"}
        once = _canonicalize_generated_email(
            raw,
            tone_preset="friendly",
            profile=profile,
            seed_baseline="asking my professor for a deadline extension",
        )
        twice = _canonicalize_generated_email(
            once,
            tone_preset="friendly",
            profile=profile,
            seed_baseline="asking my professor for a deadline extension",
        )
        self.assertEqual(once, twice)
        self.assertNotIn("Thankfully", once)
        self.assertNotIn("assignment .", once)
        self.assertIn("ask for an extension", once)
        self.assertTrue(once.endswith("Best,\nEshan"), once)
        self.assertEqual(len(re.findall(r"(?m)^(?:Best|Sincerely|Thanks),$", once)), 1)

    def test_filters_suppress_raw_seed_fallback_when_only_filler_survives(self) -> None:
        settings = {
            "tonePreset": "friendly",
            "length": "medium",
            "complexity": "standard",
            "profile": {},
        }
        draft = (
            "Subject: Sink\n\nHi there,\n\nI hope you're well.\n\n"
            "The sink in my apartment needs a plumber immediately.\n\n"
            "Best,\n[Your Name]"
        )
        out = apply_generate_hard_filters(
            draft,
            format_type="email",
            settings=settings,
            seed_baseline="tell my landlord the sink is leaking, need someone this week",
        )
        body = _parse_email_sections(out)["body"].lower()
        self.assertTrue(body.strip())
        self.assertIn("sink", body)
        self.assertNotIn("apartment", out.lower())
        self.assertNotIn("plumber", out.lower())

    def test_short_informational_note_is_included(self) -> None:
        draft = (
            "Subject: Extension\n\nHi there,\n\n"
            "I'm writing to request an extension.\n\nBest,\n[Your Name]"
        )
        out = _inject_informational_content(
            draft,
            "I have a family emergency this week.",
            format_type="email",
            length="short",
        )
        self.assertIn("family emergency this week", out.lower())
        self.assertLessEqual(_count_body_sentences(out, "email"), 2)

    def test_typography_removes_placeholder_residue(self) -> None:
        self.assertEqual(
            _clean_generate_typography("Submit the assignment by ?"),
            "Submit the assignment?",
        )
        self.assertEqual(
            _clean_generate_typography(
                "Would it be possible to have more time' extension?"
            ),
            "Would it be possible to have more time?",
        )
        self.assertEqual(
            _clean_generate_typography(
                "Would you be willing to have more time? Could you grant an additional deadline?"
            ),
            "Would you be willing to grant an extension? Could you grant an extension?",
        )


class FabricationHardeningTests(unittest.TestCase):
    def test_role_mention_injector_is_noop(self) -> None:
        seed = "complain to the HOA board about neighbor construction noise"
        polluted = (
            "Subject: Noise\n\nHi,\n\n"
            "I'm writing as your neighbor to ask that you trim the hedge.\n\n"
            "I need HOA approval before repainting the front door.\n\n"
            "Construction at 214 Willow is too loud before 8am.\n\n"
            "Thanks,\nFrank"
        )
        cleaned = apply_generate_hard_filters(
            polluted,
            format_type="email",
            settings={"tonePreset": "blunt", "length": "medium", "complexity": "standard"},
            seed_baseline=seed,
        )
        lower = cleaned.lower()
        self.assertNotIn("trim the hedge", lower)
        self.assertNotIn("front door", lower)
        self.assertEqual(
            _ensure_seed_role_mentions(
                polluted, format_type="email", seed_baseline=seed
            ),
            polluted,
        )

    def test_calendar_since_is_not_a_reason_hint(self) -> None:
        self.assertFalse(
            _seed_states_a_reason(
                "ask landlord to fix the heater, out since Tuesday"
            )
        )
        self.assertTrue(
            _seed_states_a_reason(
                "need an extension since I have a family emergency"
            )
        )

    def test_seeded_next_week_survives_until_normalization(self) -> None:
        seed = "hold the reserved book until next week"
        text = "Please hold the reserved book until next week."
        cleaned = _normalize_unseeded_timing_details(text, seed)
        self.assertIn("next week", cleaned.lower())
        self.assertNotIn("more time", cleaned.lower())

        seed = "ask landlord to fix the broken heater, out since Tuesday"
        text = (
            "The heater has been out since Tuesday and is causing considerable "
            "discomfort, especially during these cold nights. Please fix it by Friday."
        )
        cleaned = _normalize_unseeded_timing_details(text, seed)
        lower = cleaned.lower()
        self.assertIn("tuesday", lower)
        self.assertNotIn("cold nights", lower)
        self.assertNotIn("considerable discomfort", lower)
        self.assertNotIn("friday", lower)

    def test_style_note_is_not_informational_content(self) -> None:
        parsed = _parse_generation_note(
            "Style: be direct, no corporate softening, do not say "
            "'I understand this may be frustrating'"
        )
        self.assertTrue(parsed["has_tone_instruction"])
        self.assertIsNone(parsed["informational_content"])
        factual = _parse_generation_note(
            "Factual: I have been on-site full time since March 2024"
        )
        self.assertEqual(
            factual["informational_content"],
            "I have been on-site full time since March 2024",
        )

        self.assertEqual(
            _permanent_note_sentence("Factual: started at Bright Path in 2021"),
            "Started at Bright Path in 2021.",
        )
        self.assertEqual(
            _permanent_note_sentence(
                "Style: be direct, no corporate softening"
            ),
            "",
        )

    def test_seeded_reason_still_strips_unforeseen_filler(self) -> None:
        seed = (
            "apologize to client Bea for the late delivery because our "
            "warehouse flooded, shipment arrives Friday"
        )
        polluted = (
            "Subject: Delay\n\nDear Sir or Madam,\n\n"
            "I apologize for the delay due to unforeseen circumstances at our end.\n\n"
            "We had a flood in our warehouse. Shipment arrives Friday.\n\n"
            "Sincerely,\nChris"
        )
        cleaned = apply_generate_hard_filters(
            polluted,
            format_type="email",
            settings={"tonePreset": "formal", "length": "medium", "complexity": "standard"},
            seed_baseline=seed,
        )
        lower = cleaned.lower()
        self.assertNotIn("unforeseen circumstances", lower)
        self.assertIn("warehouse", lower)
        self.assertIn("friday", lower)

        seed = (
            "remind client Dana at Northfield Design that invoice #2291 "
            "for $1,450 was due last Friday"
        )
        polluted = (
            "Subject: Invoice\n\nDear Sir or Madam,\n\n"
            "The Friday standup is moving. Invoice #2291 for $1,450 is due.\n\n"
            "Sincerely,\nMiguel"
        )
        cleaned = apply_generate_hard_filters(
            polluted,
            format_type="email",
            settings={"tonePreset": "formal", "length": "short", "complexity": "simple"},
            seed_baseline=seed,
        )
        self.assertNotIn("standup", cleaned.lower())


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
