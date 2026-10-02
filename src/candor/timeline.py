"""Transaction-time gate. Nothing is ranked, cited, or shown before it exists.

Inequalities are the ones in `eval_harness/records.py`:

- a unit is visible when `available_at <= as_of`
- a Slack target is gone when its deletion time is `<= as_of`
- an edit replaces the target text when the edit time is `<= as_of`
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from candor.models import Corpus, Record


def is_available(record: Record, as_of: datetime, deleted: dict[str, datetime]) -> bool:
    """Return whether this unit exists at `as_of`."""
    if record.available_at > as_of:
        return False
    removed_at = deleted.get(record.id)
    if removed_at is not None and removed_at <= as_of:
        return False
    return True


def text_as_of(record: Record, as_of: datetime, edits: dict[str, list[tuple[datetime, str]]]) -> str:
    """Return the unit text with every edit at or before `as_of` applied."""
    newer = [text for when, text in edits.get(record.id, []) if when <= as_of]
    if not newer:
        return record.text
    return record.text.partition(": ")[0] + ": " + newer[-1] + " (edited)"


def visible(corpus: Corpus, as_of: datetime) -> list[Record]:
    """Units that exist at `as_of`, with edit text applied. Delivery order is preserved."""
    shown = []
    for record in corpus.records:
        if not is_available(record, as_of, corpus.deleted):
            continue
        text = text_as_of(record, as_of, corpus.edits)
        shown.append(record if text == record.text else replace(record, text=text))
    return shown


def availability_index(corpus: Corpus) -> dict[str, datetime]:
    """Delivery time of every unit, plus each parent at its earliest unit.

    A whole meeting id becomes available when its first segment does. Citing the
    meeting id is still the wrong granularity; this map is what the scorer uses
    for the time-leak check.
    """
    avail = {record.id: record.available_at for record in corpus.records}
    for record in corpus.records:
        current = avail.get(record.parent_id)
        if current is None or record.available_at < current:
            avail[record.parent_id] = record.available_at
    return avail
