"""Every as_of cut must keep not-yet-delivered and deleted ids out of the top 20."""

from __future__ import annotations

import json
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from candor.ingest import load_corpus  # noqa: E402
from candor.redact import has_key_shape  # noqa: E402
from candor.retrieve import retrieve  # noqa: E402
from candor.timeline import availability_index  # noqa: E402

DATA = ROOT / "data"
GOLD = ROOT / "evals" / "memory_train.jsonl"


def _questions():
    with GOLD.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


class AsOfSweepTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.corpus = load_corpus(DATA)
        cls.avail = availability_index(cls.corpus)
        cls.questions = _questions()

    def test_each_train_question_is_clean_at_its_as_of(self):
        for item in self.questions:
            moment = datetime.fromisoformat(item["as_of"])
            for stem in (False, True):
                self._assert_clean(item["question"], moment, stem)

    def test_every_question_is_clean_around_edits_and_deletions(self):
        moments = [datetime.fromisoformat("2026-09-01T00:00:00-07:00")]
        for when in self.corpus.deleted.values():
            moments.extend((when - timedelta(seconds=1), when))
        for versions in self.corpus.edits.values():
            for when, _text in versions:
                moments.extend((when - timedelta(seconds=1), when))
        for moment in moments:
            for item in self.questions:
                self._assert_clean(item["question"], moment, True)

    def _assert_clean(self, question, moment, stem):
        ranked = retrieve(self.corpus, question, moment, stem=stem)
        self.assertLessEqual(len(ranked), 20)
        for record in ranked:
            self.assertLessEqual(self.avail[record.id], moment, record.id)
            removed = self.corpus.deleted.get(record.id)
            if removed is not None:
                self.assertGreater(removed, moment, record.id)

    def test_deleted_message_is_absent_after_its_timestamp(self):
        target = "SL-DM-AB-0915-2"
        when = self.corpus.deleted[target]
        before = retrieve(self.corpus, "staging key eta eval", when - timedelta(seconds=1), stem=False)
        after = retrieve(self.corpus, "staging key eta eval", when, stem=False)
        self.assertIn(target, {record.id for record in before})
        self.assertNotIn(target, {record.id for record in after})
        from candor.answer import placeholder

        answer, _sources, _abstained = placeholder([self.corpus.by_id()[target]])
        self.assertFalse(has_key_shape(answer))
