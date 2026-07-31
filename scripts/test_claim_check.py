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

    def test_soft_connectives_not_fabricated(self) -> None:
        findings = claim_check_draft(
            "Subject: Quote\n\nDear Lena,\n\n"
            "I am writing to inform you and ask you to review and reflect on "
            "the quote from Cobalt Tools CT-552. Please proceed accordingly "
            "by Friday.\n\nSincerely,\nHank Morris",
            seed=(
                "tell buyer Lena at Cobalt Tools that quote CT-552 needs revision "
                "because steel costs rose, reply by Friday"
            ),
            profile={"fullName": "Hank Morris"},
        )
        fabricated = {
            f.detail.lower()
            for f in findings
            if f.classification == "fabricated"
        }
        for soft in ("inform", "review", "reflect", "proceed"):
            self.assertNotIn(soft, fabricated, fabricated)
        grounded = " ".join(
            f.detail.lower()
            for f in findings
            if f.classification in {"grounded", "restatement"}
        )
        self.assertIn("ct-552", grounded)

    def test_profile_membership_id_missing_when_dropped(self) -> None:
        """IDs like IC-4471 live on the profile and must be flagged if absent."""
        draft = (
            "Subject: Cancel Membership\n\nDear Ironclad Fitness,\n\n"
            "Please cancel my membership. I am moving end of the month.\n\n"
            "Sincerely,\nHalle Jorgensen"
        )
        findings = claim_check_draft(
            draft,
            seed="cancel my membership at Ironclad Fitness, moving to a new city end of the month",
            profile={
                "fullName": "Halle Jorgensen",
                "member_id": "IC-4471",
            },
        )
        missing = {
            f.detail.upper().replace(" ", "")
            for f in findings
            if f.classification == "missing"
        }
        self.assertTrue(
            any("IC4471" in m or "IC-4471" in m for m in missing)
            or any(
                f.classification == "missing" and "4471" in f.detail
                for f in findings
            ),
            [(f.classification, f.detail, f.expected_source) for f in findings],
        )
        # Present ID is grounded, not missing.
        findings_ok = claim_check_draft(
            draft.replace(
                "Please cancel my membership.",
                "Please cancel membership IC-4471.",
            ),
            seed="cancel my membership at Ironclad Fitness, moving to a new city end of the month",
            profile={
                "fullName": "Halle Jorgensen",
                "member_id": "IC-4471",
            },
        )
        missing_ok = [
            f.detail for f in findings_ok if f.classification == "missing"
        ]
        self.assertFalse(
            any("4471" in m for m in missing_ok),
            missing_ok,
        )

    def test_account_id_va_style_missing(self) -> None:
        findings = claim_check_draft(
            "Subject: Cancel\n\nHi,\n\n"
            "Cancel my Vantage Analytics Pro subscription. Overcharged twice.\n\n"
            "Thanks,\nOtis Calloway",
            seed="cancel my subscription to Vantage Analytics Pro, been overcharged twice already",
            profile={"fullName": "Otis Calloway", "account": "VA-90213"},
        )
        missing = " ".join(
            f.detail for f in findings if f.classification == "missing"
        ).upper()
        self.assertIn("VA-90213", missing.replace(" ", ""), missing)
        # Compact form also acceptable in assertion after norm — check digits.
        self.assertTrue(
            any(
                f.classification == "missing" and "90213" in f.detail
                for f in findings
            ),
            [(f.classification, f.detail) for f in findings],
        )

    def test_quantity_noun_three_reminders_missing(self) -> None:
        findings = claim_check_draft(
            "Subject: Utilities\n\nHi Kevin,\n\n"
            "You owe $340 for last month's utilities. Pay soon.\n\n"
            "Thanks,\nPriya Shah",
            seed=(
                "tell roommate Kevin he owes $340 for utilities from last month "
                "and it's been three reminders now"
            ),
            profile={"fullName": "Priya Shah"},
        )
        missing = [
            f.detail.lower() for f in findings if f.classification == "missing"
        ]
        self.assertTrue(
            any("three reminders" == m or "three reminders" in m for m in missing),
            missing,
        )
        # Contiguous phrase present → not missing, even if words appear apart.
        findings_ok = claim_check_draft(
            "Subject: Utilities\n\nHi Kevin,\n\n"
            "You owe $340 for last month's utilities and it's been three reminders now.\n\n"
            "Thanks,\nPriya Shah",
            seed=(
                "tell roommate Kevin he owes $340 for utilities from last month "
                "and it's been three reminders now"
            ),
            profile={"fullName": "Priya Shah"},
        )
        missing_ok = [
            f.detail.lower() for f in findings_ok if f.classification == "missing"
        ]
        self.assertFalse(
            any("three reminders" in m for m in missing_ok),
            missing_ok,
        )

    def test_quantity_noun_not_satisfied_by_scattered_tokens(self) -> None:
        findings = claim_check_draft(
            "Subject: Utilities\n\nHi Kevin,\n\n"
            "Three days ago I sent reminders about the $340 utilities bill.\n\n"
            "Thanks,\nPriya Shah",
            seed=(
                "tell roommate Kevin he owes $340 for utilities from last month "
                "and it's been three reminders now"
            ),
            profile={"fullName": "Priya Shah"},
        )
        missing = [
            f.detail.lower() for f in findings if f.classification == "missing"
        ]
        self.assertTrue(
            any("three reminders" in m for m in missing),
            missing,
        )

    def test_overcharged_twice_quantity_missing(self) -> None:
        findings = claim_check_draft(
            "Subject: Cancel\n\nHi,\n\n"
            "Cancel my Vantage Analytics Pro subscription.\n\n"
            "Thanks,\nOtis Calloway",
            seed="cancel my subscription to Vantage Analytics Pro, been overcharged twice already",
            profile={"fullName": "Otis Calloway", "account": "VA-90213"},
        )
        missing = [
            f.detail.lower() for f in findings if f.classification == "missing"
        ]
        self.assertTrue(
            any("overcharged twice" in m for m in missing),
            missing,
        )

    def test_deadline_implied_by_extension_seed(self) -> None:
        findings = claim_check_draft(
            "Subject: Extension\n\nDear Imran,\n\n"
            "I am writing to request an extension of three days on the "
            "submission deadline for the ethics essay.\n\nSincerely,\nSofi Tran",
            seed="ask professor Imran for a three-day extension on the ethics essay",
            profile={"fullName": "Sofi Tran"},
        )
        fabricated = {
            f.detail.lower()
            for f in findings
            if f.classification == "fabricated"
        }
        self.assertNotIn("deadline", fabricated, fabricated)
        self.assertNotIn("submission", fabricated, fabricated)
        # Still flag real invents.
        findings2 = claim_check_draft(
            "Subject: Lunch\n\nHi there,\n\n"
            "Please send lunch boxes for the wedding guests at our event.\n\n"
            "Best,\nAlex Rivera",
            seed="email the caterer about the lunch boxes",
            profile={"fullName": "Alex Rivera"},
        )
        fabricated2 = " ".join(
            f.detail.lower()
            for f in findings2
            if f.classification == "fabricated"
        )
        self.assertTrue(
            any(tok in fabricated2 for tok in ("wedding", "guests", "event")),
            fabricated2,
        )

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
