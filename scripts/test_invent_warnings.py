#!/usr/bin/env python3
"""Unit tests for general invent-detail warnings in the generate matrix runner."""

from __future__ import annotations

import unittest

from scripts.run_generate_matrices import evaluate, invent_detail_warnings


class InventDetailWarningTests(unittest.TestCase):
    def test_flags_cake_flavors_not_in_idea(self) -> None:
        case = {
            "idea": "email the bakery about the cake",
            "settings": {"profile": "name: Jules Romero", "permanent_note": ""},
        }
        output = (
            "Subject: Cake Order\n\nHi there,\n\n"
            "I'd like a vanilla and chocolate layer cake, each layer 6 inches, "
            "iced in white frosting with fresh berries.\n\nBest,\nJules Romero"
        )
        flags = invent_detail_warnings(case, output)
        joined = " ".join(flags)
        self.assertTrue(
            any(tok in joined for tok in ("vanilla", "chocolate", "frosting", "berries")),
            flags,
        )
        # Seed nouns and signature must not be flagged as invents.
        self.assertNotIn("cake", flags)
        self.assertNotIn("bakery", flags)
        self.assertNotIn("jules", flags)
        self.assertNotIn("romero", flags)

    def test_flags_vet_visit_context(self) -> None:
        case = {
            "idea": "email the vet about the cat",
            "settings": {"profile": "name: Noah Fitzgerald", "permanent_note": ""},
        }
        output = (
            "Subject: Cat\n\nHi there,\n\n"
            "I am writing about my cat's recent veterinary visit. "
            "My cat had a physical examination and received treatment "
            "for an ongoing issue.\n\nBest,\nNoah Fitzgerald"
        )
        flags = invent_detail_warnings(case, output)
        joined = " ".join(flags)
        self.assertTrue(
            any(
                tok in joined
                for tok in ("veterinary", "visit", "examination", "treatment")
            ),
            flags,
        )

    def test_dense_invoice_keeps_seed_terms_unflagged(self) -> None:
        case = {
            "idea": (
                "remind client Priya at Northwind Labs that invoice NL-904 "
                "for $880 was due last Friday"
            ),
            "settings": {"profile": "name: Omar Farouk", "permanent_note": ""},
        }
        output = (
            "Subject: Invoice Due Reminder\n\nDear Priya,\n\n"
            "Invoice from Northwind Labs NL-904 for $880 is overdue as the "
            "payment was due last Friday.\n\nSincerely,\nOmar Farouk"
        )
        flags = invent_detail_warnings(case, output)
        for keep in ("priya", "northwind", "nl-904", "$880", "friday"):
            self.assertNotIn(keep, flags, flags)

    def test_warnings_do_not_fail_evaluate(self) -> None:
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
        issues, warnings = evaluate(case, 200, {}, output)
        self.assertEqual(issues, [])
        self.assertTrue(warnings)
        self.assertTrue(warnings[0].startswith("possible invent:"))


if __name__ == "__main__":
    unittest.main()
