"""Stemmer and synonym joins the ranker depends on."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from candor.textnorm import analyze, learn_lexicon, stem_token  # noqa: E402


class TextTests(unittest.TestCase):
    def test_inflections_share_a_stem(self):
        self.assertEqual(stem_token("slipped"), stem_token("slip"))
        self.assertEqual(stem_token("slipping"), stem_token("slip"))
        self.assertEqual(stem_token("moved"), stem_token("move"))
        self.assertEqual(stem_token("moving"), stem_token("move"))
        self.assertEqual(stem_token("launching"), stem_token("launch"))
        self.assertEqual(stem_token("delayed"), stem_token("delay"))

    def test_slip_and_move_share_a_synonym(self):
        slip = set(analyze("why did the launch slip", stem=True))
        move = set(analyze("the date was moved", stem=True))
        self.assertIn("slip", slip)
        self.assertIn("slip", move)

    def test_plain_analysis_keeps_slip_and_move_apart(self):
        slip = set(analyze("why did the launch slip", stem=False))
        move = set(analyze("the date was moved", stem=False))
        self.assertIn("slip", slip)
        self.assertNotIn("slip", move)

    def test_proposal_and_flight_join(self):
        proposed = set(analyze("the proposal we proposed", stem=True))
        propose = set(analyze("we propose", stem=True))
        self.assertTrue(propose <= proposed)
        self.assertIn("flight", set(analyze("the flight", stem=True)))
        self.assertIn("flight", set(analyze("we fly", stem=True)))
        self.assertIn("flight", set(analyze("flying out", stem=True)))

    def test_query_expansion_uses_attested_forms_only(self):
        learn_lexicon(["The SSO rollout is separate.", "Board deck prep is Friday."])
        expanded = analyze("single sign-on and the preparation", stem=True, expand=True)
        self.assertIn("sso", expanded)
        self.assertIn("prep", expanded)
        plain = analyze("single sign-on and the preparation", stem=True, expand=False)
        self.assertNotIn("sso", plain)
        self.assertNotIn("prep", plain)

    def test_dates_and_amounts_stay_whole(self):
        tokens = analyze("p95 was 1.8 and the fee is $18 on 10/21", stem=True)
        self.assertIn("1.8", tokens)
        self.assertIn("10/21", tokens)
        self.assertTrue(any(token.endswith("18") for token in tokens))
