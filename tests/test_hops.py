"""Anchor, join, and open-item hops on small made-up records, plus the explain trace."""

from __future__ import annotations

import dataclasses
import os
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ["CANDOR_WRITER"] = "deterministic"

from candor import hops  # noqa: E402
from candor.explain import explain_text  # noqa: E402
from candor.ingest import load_corpus  # noqa: E402
from candor.models import Record  # noqa: E402
from candor.retrieve import retrieve  # noqa: E402

START = datetime(2026, 1, 5, 9, 0, tzinfo=hops.LA)
OWNER = "Pat Owner"


def _record(rid: str, text: str, author: str = "Kim Peer", hours: int = 0, source: str = "slack",
            participants: tuple[str, ...] = (OWNER, "Kim Peer")) -> Record:
    when = START + timedelta(hours=hours)
    return Record(
        id=rid, parent_id=rid, source=source, kind="message", author=author, author_id=None,
        participants=participants, event_time=when, available_at=when, text=text, body=text,
    )


class AnchorTests(unittest.TestCase):
    def test_directions(self):
        self.assertEqual(hops.find_anchor("What did I send after the vendor call?").direction, "after")
        self.assertEqual(hops.find_anchor("What was agreed before the review?").direction, "before")
        day = hops.find_anchor("What happened the day after the offsite?")
        self.assertEqual((day.direction, day.offset_days), ("day", 1))
        self.assertIsNone(hops.find_anchor("Who owns the billing service?"))

    def test_wrong_side(self):
        anchor = hops.Anchor("vendor call", "after")
        call = _record("A", "vendor call notes", hours=0)
        earlier = _record("B", "unrelated", hours=-5)
        later = _record("C", "unrelated", hours=5)
        self.assertTrue(hops.wrong_side(anchor, call, call.event_time, earlier))
        self.assertFalse(hops.wrong_side(anchor, call, call.event_time, later))


class JoinTests(unittest.TestCase):
    def test_only_terms_shared_by_two_records(self):
        seeds = [
            _record("A", "the zephyr migration needs the kestrel cluster"),
            _record("B", "kestrel cluster capacity for zephyr"),
            _record("C", "lunch menu tomorrow"),
        ]
        pool = seeds + [_record("D", "kestrel zephyr again"), _record("E", "lunch plans")]
        query = hops.join_query("When does the migration finish?", seeds, pool)
        self.assertIn("kestrel", query)
        self.assertNotIn("lunch", query)

    def test_rrf_rewards_agreement(self):
        a, b, c = _record("A", "a"), _record("B", "b"), _record("C", "c")
        merged = [record.id for _score, record in hops.rrf([([a, b, c], 1.0), ([b, c], 0.5)])]
        self.assertEqual(merged[0], "B")


class OpenItemTests(unittest.TestCase):
    def test_promise_closed_by_the_promiser(self):
        promise = _record("P", "I'll send the vendor contract draft tomorrow.", author="Kim Peer")
        done = _record("D", "Sent the vendor contract draft, attached.", author="Kim Peer", hours=20)
        items = hops.commitments([promise, done], OWNER)
        self.assertEqual([item.record.id for item in items], ["P"])
        self.assertTrue(hops.completed(items[0], [promise, done]))

    def test_a_promise_without_a_subject(self):
        pool = [
            _record("P", "👍 will send the pricing sheet tonight", author="Kim Peer"),
            _record("Q", "The team will send nothing new.", author="Kim Peer", hours=1),
            _record("R", "Who will review it?", author="Kim Peer", hours=2),
        ]
        self.assertEqual([item.record.id for item in hops.commitments(pool, OWNER)], ["P"])

    def test_someone_else_does_not_close_it(self):
        promise = _record("P", "I'll send the vendor contract draft tomorrow.", author="Kim Peer")
        other = _record("D", "Sent the vendor contract draft.", author="Lee Third", hours=20)
        self.assertEqual([r.id for r in hops.open_items("What is still open?", [promise, other], OWNER)], ["P"])

    def test_same_person_across_sources(self):
        promise = _record("P", "I'll send the vendor contract draft tomorrow.", author="Kim Peer")
        mail = _record("D", "Here's the vendor contract draft.", author="Kim Peer <kim@peer.example>", hours=20, source="gmail")
        self.assertEqual(hops.open_items("What is still open?", [promise, mail], OWNER), [])

    def test_not_a_commitment(self):
        pool = [
            _record("N", "I will not send anything until legal signs off."),
            _record("C", "assistant: I'll write a summary for you.", author="Assistant", source="chatgpt"),
            _record("M", "We'll send the prospectus.", author="Events <partners@events.example>", source="gmail"),
        ]
        self.assertEqual(hops.commitments(pool, OWNER), [])

    def test_owe_keeps_the_owners_debts(self):
        mine = _record("R", "Can you send me the renewal numbers?", author="Kim Peer")
        theirs = _record("T", "I'll review the renewal numbers.", author="Kim Peer", hours=1)
        found = hops.open_items("What do I still owe Kim?", [mine, theirs], OWNER)
        self.assertEqual([r.id for r in found], ["R"])


class StatusTests(unittest.TestCase):
    def _thread(self, question):
        from candor import retrieve as module
        mails = [dataclasses.replace(_record(rid, "renewal terms", source="gmail", hours=hours), thread_id="T")
                 for rid, hours in (("M1", 0), ("M2", 5), ("M3", 10))]
        added = module._expand([(1.0, mails[0])], {}, {"T": mails}, set(), 3, set(), question, hop=1)
        return {record.id: score for score, record in added}

    def test_status_question_puts_the_newest_reply_first(self):
        scores = self._thread("Has the vendor signed the renewal yet?")
        self.assertGreater(scores["M3"], 1.0)
        self.assertLess(scores["M2"], 1.0)

    def test_other_questions_keep_replies_below_the_seed(self):
        scores = self._thread("What were the renewal terms?")
        self.assertTrue(all(score < 1.0 for score in scores.values()))


class TraceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.corpus = load_corpus()
        cls.as_of = datetime.fromisoformat("2026-09-18T18:00:00-07:00")

    def test_trace_does_not_change_retrieval(self):
        question = "What did I send after the planning meeting?"
        trace: dict = {}
        with_trace = retrieve(self.corpus, question, self.as_of, stem=True, trace=trace)
        plain = retrieve(self.corpus, question, self.as_of, stem=True)
        self.assertEqual([r.id for r in with_trace], [r.id for r in plain])
        self.assertIn("anchor", trace)

    def test_explain_shows_hops(self):
        text = explain_text(self.corpus, "What do I still owe people?", self.as_of)
        self.assertIn("Retrieval hops", text)
        self.assertIn("Open items (no later completion):", text)


if __name__ == "__main__":
    unittest.main()
