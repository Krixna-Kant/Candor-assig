"""Sarah Kim and Sarah Patel stay distinct. Unnamed speakers are not people."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from candor.entities import build_directory  # noqa: E402
from candor.ingest import load_corpus  # noqa: E402
from candor.trust import is_untrusted  # noqa: E402


class EntityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.corpus = load_corpus()
        cls.directory = build_directory(cls.corpus)

    def test_two_sarahs_do_not_merge(self):
        keys = {person.key for person in self.directory.people}
        self.assertIn("sarah kim", keys)
        self.assertIn("sarah patel", keys)
        self.assertIn("sarah", self.directory.ambiguous_first)
        named = self.directory.resolve_question("What did Sarah Patel say about pricing?")
        self.assertIn("sarah patel", named.wanted)
        self.assertIn("sarah kim", named.blocked)
        bare = self.directory.resolve_question("What did Sarah say?")
        self.assertEqual(set(bare.wanted), set())

    def test_rachel_is_a_person_and_speaker_4_is_not(self):
        keys = {person.key for person in self.directory.people}
        self.assertIn("rachel gomez", keys)
        self.assertNotIn("speaker 4", keys)

    def test_planted_instruction_is_untrusted_and_still_indexed(self):
        flagged = [record for record in self.corpus.records if is_untrusted(record)]
        self.assertTrue(flagged)
        self.assertTrue(any("ignore" in record.text.lower() for record in flagged))
