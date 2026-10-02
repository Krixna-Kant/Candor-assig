"""Records the memory can cite, plus the edit and deletion maps that change them."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class Record:
    """One citable unit. `text` matches the harness display string before edits apply."""

    id: str
    parent_id: str
    source: str
    kind: str
    author: str | None
    author_id: str | None
    participants: tuple[str, ...]
    event_time: datetime
    available_at: datetime
    text: str
    body: str
    thread_id: str | None = None
    target_id: str | None = None
    channel: str | None = None
    speaker_confidence: float | None = None
    speaker_identified: bool = True


@dataclass
class Corpus:
    """Every unit in `data/`, in delivery order, with Slack version history."""

    records: list[Record]
    deleted: dict[str, datetime] = field(default_factory=dict)
    edits: dict[str, list[tuple[datetime, str]]] = field(default_factory=dict)

    def by_id(self) -> dict[str, Record]:
        return {record.id: record for record in self.records}
