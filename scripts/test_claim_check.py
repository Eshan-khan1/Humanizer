#!/usr/bin/env python3
"""Unit tests for Generate claim checking (detection only)."""

from __future__ import annotations

import unittest

from claim_check import claim_check_draft, claim_check_summary, format_claim_checklist
from scripts.run_generate_matrices import evaluate


class ClaimCheckTests(unittest.TestCase):
    def test_flags_fabricated_cake_flavors(self) -> None:
        findings = claim_check_draft(
            "Subject: Cake\n\nHi there,\n\n"
            "I'd like a vanilla and chocolate layer cake with fresh berries.\n\n"
            "Best,\nJules Romero",
            seed="email the bakery about the cake",
            permanent_note="",
            profile={"fullName": "Jules Romero"},
        )
        fabricated = {
            f.detail.lower()
            for f in findings
            if f.classification == "fabricated"
        }
        self.assertTrue(
            any(tok in " ".join(fabricated) for tok in ("vanilla", "chocolate", "berries")),
            fabricated,
        )
        grounded = {
            f.detail.lower()
            for f in findings
            if f.classification in {"grounded", "restatement"}
        }
        self.assertTrue(any("cake" in g for g in grounded), grounded)
        self.assertFalse(any("jules" in f for f in fabricated))

    def test_flags_missing_fridays_from_factual_note(self) -> None:
        findings = claim_check_draft(
            "Subject: Remote\n\nDear Pauline,\n\n"
            "I am writing to request remote work starting in October.\n\n"
            "We already covered this in July.\n\nSincerely,\nCraig Nunez",
            seed="ask director Pauline for remote Fridays starting in October",
            permanent_note="Factual: My team already piloted remote Fridays in July",
            profile={"fullName": "Craig Nunez"},
        )
        missing = {
            f.detail.lower()
            for f in findings
            if f.classification == "missing"
        }
        self.assertTrue(
            any("friday" in m for m in missing),
            missing,
        )
        # July / October / Pauline should be grounded, not missing.
        grounded = " ".join(
            f.detail.lower()
            for f in findings
            if f.classification in {"grounded", "restatement"}
        )
        self.assertIn("october", grounded)
        self.assertIn("july", grounded)

    def test_restates_costs_rose(self) -> None:
        findings = claim_check_draft(
            "Subject: Quote\n\nDear Lena,\n\n"
            "Steel prices have increased since quote CT-552.\n\n"
            "Please revise by Friday.\n\nSincerely,\nHank Morris",
            seed=(
                "tell buyer Lena at Cobalt Tools that quote CT-552 needs revision "
                "because steel costs rose, reply by Friday"
            ),
            profile={"fullName": "Hank Morris"},
        )
        by_detail = {f.detail.lower(): f.classification for f in findings}
        # prices/increased should be restatement or grounded, not fabricated.
        for key, classification in by_detail.items():
            if "price" in key or "increas" in key:
                self.assertIn(classification, {"grounded", "restatement"}, key)
        fabricated = [
            f.detail for f in findings if f.classification == "fabricated"
        ]
        self.assertNotIn("CT-552", fabricated)
        self.assertNotIn("Friday", fabricated)

    def test_lunch_boxes_missing_when_singularized_poorly(self) -> None:
        # Singular "lunch box" is a restatement of "lunch boxes", so not missing.
        findings = claim_check_draft(
            "Subject: Lunch\n\nHi there,\n\n"
            "I'm writing about the lunch box arrangements for our event.\n\n"
            "Best,\nAlex Rivera",
            seed="email the caterer about the lunch boxes",
            profile={"fullName": "Alex Rivera"},
        )
        missing = [f for f in findings if f.classification == "missing"]
        self.assertFalse(
            any("lunch" in f.detail.lower() for f in missing),
            missing,
        )
        # "event" is fabricated; "caterer" may be missing from draft.
        fabricated = " ".join(
            f.detail.lower() for f in findings if f.classification == "fabricated"
        )
        self.assertIn("event", fabricated)

    def test_checklist_format_and_evaluate_wiring(self) -> None:
        case = {
            "idea": "email the bakery about the cake",
            "feature": "generate",
            "settings": {"profile": "name: Jules Romero", "permanent_note": ""},
            "checks": {"must_include_entities": ["cake"]},
        }
        output = (
            "Subject: Cake\n\nHi there,\n\n"
            "Please prepare a vanilla cake with berries.\n\nBest,\nJules Romero"
        )
        issues, warnings, claim_lines = evaluate(case, 200, {}, output)
        self.assertEqual(issues, [])
        self.assertTrue(warnings)
        self.assertIn("fabricated", warnings[0])
        joined = "\n".join(claim_lines)
        self.assertIn("[fabricated]", joined)
        self.assertIn("vanilla", joined.lower())
        summary = claim_check_summary(claim_check_draft(output, seed=case["idea"]))
        self.assertIn("fabricated", summary)
        self.assertTrue(any(line.startswith("  [") for line in format_claim_checklist(
            claim_check_draft(output, seed=case["idea"], profile={"fullName": "Jules Romero"})
        )))


if __name__ == "__main__":
    unittest.main()
