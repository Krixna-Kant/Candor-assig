"""Availability must agree with eval_harness/records.py at the exact boundaries."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

_spec = importlib.util.spec_from_file_location("harness_records", ROOT / "eval_harness" / "records.py")
harness = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(harness)

from candor.ingest import load_corpus  # noqa: E402
from candor.timeline import availability_index, visible  # noqa: E402

DATA = ROOT / "data"


def _enable_utf8_oracle():
    """The harness opens data files with the locale encoding. Force UTF-8."""
    import builtins
    import pathlib

    origin_open = builtins.open

    def open_utf8(file, mode="r", *args, **kwargs):
        if "b" not in mode and "encoding" not in kwargs:
            kwargs["encoding"] = "utf-8"
        return origin_open(file, mode, *args, **kwargs)

    builtins.open = open_utf8
    origin_read = pathlib.Path.read_text

    def read_text(self, encoding=None, errors=None):
        return origin_read(self, encoding=encoding or "utf-8", errors=errors)

    pathlib.Path.read_text = read_text


_enable_utf8_oracle()


class TimelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.corpus = load_corpus(DATA)
        cls.units, cls.deleted, cls.edits = harness.load(DATA)

    def test_unit_set_matches_harness(self):
        ours = {record.id: record for record in self.corpus.records}
        theirs = {unit.id: unit for unit in self.units}
        self.assertEqual(set(ours), set(theirs))
        self.assertEqual(len(ours), 1316)
        for unit_id, unit in theirs.items():
            record = ours[unit_id]
            self.assertEqual(record.available_at, unit.time, unit_id)
            self.assertEqual(record.parent_id, unit.record, unit_id)
            self.assertEqual(record.text, unit.text, unit_id)

    def test_deletions_and_edits_match_harness(self):
        self.assertEqual(self.corpus.deleted, self.deleted)
        self.assertEqual(self.corpus.edits, self.edits)

    def test_parent_availability_matches_harness(self):
        self.assertEqual(availability_index(self.corpus), harness.context(DATA)["avail"])

    def test_whole_meeting_id_is_available_from_its_earliest_segment(self):
        avail = availability_index(self.corpus)
        harness_avail = harness.context(DATA)["avail"]
        unit_ids = {record.id for record in self.corpus.records}
        meetings = {record.parent_id for record in self.corpus.records if record.source == "meeting"}
        self.assertEqual(len(meetings), 8)
        for meeting_id in meetings:
            earliest = min(
                record.available_at for record in self.corpus.records if record.parent_id == meeting_id
            )
            self.assertEqual(avail[meeting_id], earliest, meeting_id)
            self.assertEqual(harness_avail[meeting_id], earliest, meeting_id)
            self.assertNotIn(meeting_id, unit_ids, meeting_id)

    def test_visible_text_matches_harness_at_boundaries(self):
        moments = self._boundary_moments()
        for moment in moments:
            expected = {unit.id: unit.text for unit in harness.visible(DATA, moment)}
            got = {record.id: record.text for record in visible(self.corpus, moment)}
            self.assertEqual(got, expected, moment.isoformat())

    def test_edit_replaces_text_at_the_exact_timestamp(self):
        when = self.corpus.edits["SL-RP-0916-1"][0][0]
        before = self._text_at("SL-RP-0916-1", when - timedelta(seconds=1))
        at_edit = self._text_at("SL-RP-0916-1", when)
        self.assertIn("60/64", before)
        self.assertNotIn("61/64", before)
        self.assertIn("61/64", at_edit)
        self.assertNotIn("SL-EV-0916-EDIT1", self._ids(when - timedelta(seconds=1)))
        self.assertIn("SL-EV-0916-EDIT1", self._ids(when))

    def test_deletion_removes_the_target_at_the_exact_timestamp(self):
        for target, event in (("SL-DM-AB-0915-2", "SL-EV-0915-DEL1"), ("SL-SALES-0915-1", "SL-EV-0915-DEL2")):
            when = self.corpus.deleted[target]
            self.assertIn(target, self._ids(when - timedelta(seconds=1)))
            self.assertNotIn(target, self._ids(when))
            self.assertIn(event, self._ids(when))

    def test_calendar_snapshot_is_unavailable_before_updated(self):
        event = self.corpus.by_id()["CAL-BOARDPREP"]
        self.assertNotIn(event.id, self._ids(event.available_at - timedelta(seconds=1)))
        self.assertIn(event.id, self._ids(event.available_at))

    def test_meeting_segments_appear_only_after_they_end(self):
        segments = [unit for unit in self.units if unit.record == "MTG-0908-PLAN"]
        first = min(unit.time for unit in segments)
        last = max(unit.time for unit in segments)
        midpoint = first + (last - first) / 2
        shown = {record.id for record in visible(self.corpus, midpoint) if record.parent_id == "MTG-0908-PLAN"}
        expected = {unit.id for unit in segments if unit.time <= midpoint}
        self.assertEqual(shown, expected)
        self.assertTrue(shown)
        self.assertLess(len(shown), len(segments))
        earlier = {record.parent_id for record in visible(self.corpus, first - timedelta(seconds=1))}
        self.assertNotIn("MTG-0908-PLAN", earlier)

    def _boundary_moments(self):
        moments = []
        for when in self.corpus.deleted.values():
            moments.extend((when - timedelta(seconds=1), when, when + timedelta(seconds=1)))
        for versions in self.corpus.edits.values():
            for when, _text in versions:
                moments.extend((when - timedelta(seconds=1), when, when + timedelta(seconds=1)))
        board = self.corpus.by_id()["CAL-BOARDPREP"]
        moments.extend((board.available_at - timedelta(seconds=1), board.available_at))
        first = self.corpus.records[0].available_at
        last = self.corpus.records[-1].available_at
        moments.extend((first - timedelta(seconds=1), first, last, last + timedelta(seconds=1)))
        return moments

    def _ids(self, moment):
        return {record.id for record in visible(self.corpus, moment)}

    def _text_at(self, unit_id, moment):
        for record in visible(self.corpus, moment):
            if record.id == unit_id:
                return record.text
        self.fail(f"{unit_id} missing at {moment.isoformat()}")


if __name__ == "__main__":
    unittest.main()
