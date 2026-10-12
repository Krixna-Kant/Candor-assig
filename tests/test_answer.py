"""Abstention, redaction, and the as-of text of an answer."""

from __future__ import annotations

import json
import sys
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from candor.answer import compose  # noqa: E402
from candor.explain import explain_text  # noqa: E402
from candor.ingest import load_corpus  # noqa: E402
from candor.redact import has_key_shape, redact  # noqa: E402
from candor.retrieve import retrieve  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]


def _questions(name: str) -> list[dict]:
    path = ROOT / "evals" / name
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class AnswerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.corpus = load_corpus()

    def _run(self, question: str, as_of: str):
        moment = datetime.fromisoformat(as_of)
        ranked = retrieve(self.corpus, question, moment, stem=True)
        return compose(self.corpus, question, moment, ranked)

    def test_explain_names_what_was_visible(self):
        moment = datetime.fromisoformat("2026-09-18T18:00:00-07:00")
        text = explain_text(self.corpus, "What is Dana's salary?", moment)
        self.assertIn("Visible:", text)
        self.assertIn("Abstained: yes", text)
        self.assertIn("I don't know", text)

    def test_entity_without_the_topic_abstains(self):
        answer, _sources, abstained = self._run(
            "What did Sarah Kim say about GDPR?", "2026-09-18T18:00:00-07:00",
        )
        self.assertTrue(abstained)
        self.assertIn("don't know", answer.lower())
        _text, sources, abstained = self._run(
            "What per-vehicle figure did we put in front of Acme Freight?",
            "2026-09-18T18:00:00-07:00",
        )
        self.assertFalse(abstained)
        self.assertTrue(sources)

    def test_pay_question_abstains(self):
        pay, _, abstained = self._run(
            "How much does Ben Carter earn?", "2026-09-18T18:00:00-07:00",
        )
        self.assertTrue(abstained, pay)
        self.assertIn("don't know", pay.lower())

    def test_unanswerable_topics_abstain(self):
        salary, _, abstained = self._run("What is Dana's salary?", "2026-09-18T18:00:00-07:00")
        self.assertTrue(abstained)
        self.assertIn("don't know", salary.lower())
        soc, _, abstained = self._run(
            "What did Harbor Logistics say about SOC 2?", "2026-09-18T18:00:00-07:00",
        )
        self.assertTrue(abstained)

    def test_weak_overlap_still_answers(self):
        cases = [
            "What was Sarah Kim's position on single sign-on?",
            "Which storage engine did I settle on for the ETA prototype, and why that one?",
            "What time is the board-deck preparation blocked on my schedule?",
            "What did my September 10 voice memo to Sarah Patel say, and was it sent?",
        ]
        for question in cases:
            _text, sources, abstained = self._run(question, "2026-09-18T18:00:00-07:00")
            self.assertFalse(abstained, question)
            self.assertTrue(sources, question)

    def test_train_and_probe_outputs_have_no_key_and_no_deleted_text(self):
        deleted_phrases = []
        for record in self.corpus.records:
            if record.id not in self.corpus.deleted:
                continue
            words = [word for word in redact(record.body).split() if word != "[REDACTED]"]
            if len(words) >= 6:
                deleted_phrases.append((self.corpus.deleted[record.id], " ".join(words[:6])))
        self.assertTrue(deleted_phrases)
        for name in ("memory_train.jsonl", "memory_probe.jsonl"):
            for item in _questions(name):
                answer, _sources, abstained = self._run(item["question"], item["as_of"])
                self.assertEqual(abstained, not item["answerable"], item["id"])
                self.assertFalse(has_key_shape(answer), item["id"])
                self.assertLessEqual(len(answer.split()), 120, item["id"])
                moment = datetime.fromisoformat(item["as_of"])
                for removed_at, phrase in deleted_phrases:
                    if removed_at <= moment:
                        self.assertNotIn(phrase, answer, item["id"])

    def test_edited_count_uses_the_text_at_as_of(self):
        answer, _sources, abstained = self._run(
            "How many regression cases were passing on Sep 16?",
            "2026-09-18T18:00:00-07:00",
        )
        self.assertFalse(abstained)
        self.assertIn("61", answer)
        self.assertNotIn("60/64", answer)
        self.assertNotIn("60 of 64", answer)
