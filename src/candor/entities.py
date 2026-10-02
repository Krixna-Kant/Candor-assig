"""People mentioned in the corpus. Two Sarahs stay two people."""

from __future__ import annotations

import re
from dataclasses import dataclass

from candor.models import Corpus, Record

_EMAIL = re.compile(r"([A-Za-z][^<@]{0,60}?)\s*<([^>]+)>")


@dataclass(frozen=True)
class Person:
    key: str
    full: str
    first: str
    last: str
    emails: frozenset[str]
    slack_id: str | None


@dataclass(frozen=True)
class Resolution:
    """Who a question names, and who else shares that first name."""

    wanted: frozenset[str]
    blocked: frozenset[str]


class Directory:
    def __init__(self, people: list[Person]):
        self.people = people
        self.by_key = {person.key: person for person in people}
        self.by_email = {}
        self.by_slack = {}
        firsts: dict[str, list[str]] = {}
        for person in people:
            for email in person.emails:
                self.by_email[email.lower()] = person.key
            if person.slack_id:
                self.by_slack[person.slack_id] = person.key
            firsts.setdefault(person.first, []).append(person.key)
        self.ambiguous_first = {first for first, keys in firsts.items() if len(keys) > 1}

    def resolve_question(self, question: str) -> Resolution:
        """Full names select one person. A shared first name alone selects nobody."""
        lowered = question.lower()
        wanted: set[str] = set()
        for person in self.people:
            if person.full.lower() in lowered:
                wanted.add(person.key)
        blocked: set[str] = set()
        if wanted:
            for person in self.people:
                if person.key in wanted:
                    continue
                if any(self.by_key[key].first == person.first for key in wanted):
                    blocked.add(person.key)
        return Resolution(frozenset(wanted), frozenset(blocked))

    def keys_for(self, record: Record) -> set[str]:
        found: set[str] = set()
        if record.author_id and record.author_id in self.by_slack:
            found.add(self.by_slack[record.author_id])
        if record.speaker_identified and record.author:
            for person in self.people:
                if person.full == record.author:
                    found.add(person.key)
        for raw in record.participants:
            match = _EMAIL.search(raw)
            email = (match.group(2) if match else raw).strip().lower()
            if email in self.by_email:
                found.add(self.by_email[email])
        return found


def build_directory(corpus: Corpus) -> Directory:
    """Internal Slack users, named speakers, and people who appear in email headers."""
    bucket: dict[str, dict] = {}

    def slot(full: str) -> dict:
        key = " ".join(full.split()).lower()
        return bucket.setdefault(key, {"full": " ".join(full.split()), "emails": set(), "slack_id": None})

    for record in corpus.records:
        if record.author_id and record.author_id.startswith("U") and record.speaker_identified and record.author:
            if record.author.startswith("Speaker "):
                continue
            slot(record.author)["slack_id"] = record.author_id
        if record.source == "meeting" and record.speaker_identified and record.author:
            if not record.author.startswith("Speaker "):
                slot(record.author)
        for raw in record.participants:
            match = _EMAIL.search(raw)
            if not match:
                continue
            full = match.group(1).strip()
            if not full or "@" in full:
                continue
            slot(full)["emails"].add(match.group(2).strip().lower())
    people = []
    for key, item in bucket.items():
        parts = item["full"].split()
        if len(parts) < 2:
            continue
        people.append(Person(
            key=key,
            full=item["full"],
            first=parts[0].lower(),
            last=parts[-1].lower(),
            emails=frozenset(item["emails"]),
            slack_id=item["slack_id"],
        ))
    return Directory(people)
