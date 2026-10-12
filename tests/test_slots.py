"""The slot reader: copied-words check, rewrite into plain clauses, and fallback. No network calls."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from candor import slots, writer  # noqa: E402
from candor.actions import plan  # noqa: E402
from candor.entities import build_directory  # noqa: E402
from candor.ingest import load_corpus  # noqa: E402

FAKE = writer.Settings("http://127.0.0.1:9", "test", "fake-model")
AS_OF = datetime.fromisoformat("2026-09-16T12:00:00-07:00")


def _reply(*actions: dict) -> str:
    return json.dumps({"actions": list(actions)})


class SlotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.corpus = load_corpus()

    def setUp(self):
        self.cache = tempfile.TemporaryDirectory()
        patches = [
            mock.patch.object(slots, "CACHE", Path(self.cache.name)),
            mock.patch.object(slots, "settings", return_value=FAKE),
            mock.patch.dict(os.environ, {"CANDOR_WRITER": "deterministic", "CANDOR_WRITER_STRICT": ""}),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.addCleanup(self.cache.cleanup)

    def _plan(self, command: str, reply: str) -> tuple[list[dict], str]:
        trace: dict = {}
        with mock.patch.object(writer, "_post", return_value=reply):
            return plan(self.corpus, command, AS_OF, trace), trace["reader"]

    def test_slots_become_a_plain_clause(self):
        command = "Could you ping Dana on Slack to say the mockups look great"
        actions, reader = self._plan(command, _reply({"intent": "slack", "to": ["Dana"], "say": "the mockups look great"}))
        self.assertEqual(reader, "model")
        self.assertEqual(actions[0]["type"], "slack.send_message")
        self.assertEqual(actions[0]["args"]["to"], "U04DANA")
        self.assertIn("mockups", actions[0]["args"]["text"])

    def test_invented_words_are_refused(self):
        command = "Ping Dana that the mockups look great"
        reply = _reply({"intent": "email", "to": ["review@elsewhere.example.com"], "say": "the mockups look great"})
        actions, reader = self._plan(command, reply)
        self.assertTrue(reader.startswith("fallback"))
        self.assertNotIn("review@elsewhere.example.com", json.dumps(actions))

    def test_a_question_goes_to_the_rules(self):
        actions, reader = self._plan("What's our launch date again?", _reply({"intent": "ask"}))
        self.assertEqual(actions[0]["type"], "memory.ask")

    def test_bad_json_falls_back(self):
        _actions, reader = self._plan("Thank Priya on Slack", "not json")
        self.assertTrue(reader.startswith("fallback"))

    def test_cache_skips_the_model(self):
        command = "Thank Priya on Slack"
        reply = _reply({"intent": "slack", "to": ["Priya"], "say": "Thank"})
        self._plan(command, reply)
        with mock.patch.object(writer, "_post", side_effect=AssertionError("called")):
            trace: dict = {}
            plan(self.corpus, command, AS_OF, trace)
        self.assertEqual(trace["reader"], "cache")

    def test_strict_raises(self):
        with mock.patch.dict(os.environ, {"CANDOR_WRITER_STRICT": "1"}):
            with self.assertRaises(ValueError):
                self._plan("Thank Priya on Slack", _reply({"intent": "slack", "to": ["Somebody Else"]}))

    def test_prompt_names_nobody_from_the_data(self):
        lowered = slots.SYSTEM.lower()
        for person in build_directory(self.corpus).people:
            if len(person.first) > 3:
                self.assertNotRegex(lowered, rf"\b{person.first}\b")


if __name__ == "__main__":
    unittest.main()
