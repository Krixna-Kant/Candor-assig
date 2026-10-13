"""Retrieval hops that need a first answer before the second search: anchors, joins, open items.

All three are deterministic and read only the records visible at `as_of`.

- An anchor question ("after X", "before X", "the day of X") finds the event X
  first, then searches the records on the asked side of it.
- A join takes the rarest terms and names from the best records and searches
  again; the two rankings are merged by reciprocal rank.
- An open-items question looks for requests and commitments that no later
  record completes.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from candor.bm25 import scored
from candor.models import Record
from candor.textnorm import _STOP, analyze
from candor.trust import is_untrusted

LA = ZoneInfo("America/Los_Angeles")
_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
_DATE = re.compile(
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{1,2})\b", re.IGNORECASE,
)
_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_STOP_AT = r"(?=[,?.;]|\s+(?:did|do|does|was|were|is|are|has|have|had|what|who|when|how|which|and)\b|$)"
_RELATIVE = re.compile(r"\b(after|before|since|following|until|prior to)\s+(?:the\s+|my\s+|our\s+)?(.+?)" + _STOP_AT, re.IGNORECASE)
_DAY = re.compile(
    r"\bthe day (after|before|of)\s+(?:the\s+|my\s+|our\s+)?(.+?)" + _STOP_AT
    + r"|\bthe day (?:i|we)\s+(.+?)" + _STOP_AT,
    re.IGNORECASE,
)
WINDOW = timedelta(days=7)


@dataclass(frozen=True)
class Anchor:
    phrase: str
    direction: str  # "after", "before", or "day"
    offset_days: int = 0


def find_anchor(question: str) -> Anchor | None:
    day = _DAY.search(question)
    if day:
        if day.group(1):
            offset = {"after": 1, "before": -1, "of": 0}[day.group(1).lower()]
            return Anchor(day.group(2).strip(), "day", offset)
        return Anchor(day.group(3).strip(), "day", 0)
    relative = _RELATIVE.search(question)
    if relative and len(analyze(relative.group(2), stem=True)) >= 1:
        word = relative.group(1).lower()
        direction = "before" if word in {"before", "until", "prior to"} else "after"
        return Anchor(relative.group(2).strip(), direction, 0)
    return None


def resolve(anchor: Anchor, pool: list[Record], earliest: dict[str, datetime]) -> tuple[Record, datetime] | None:
    """The record that best names the anchor event, and the time the event happened."""
    trusted = [record for record in pool if not is_untrusted(record)]
    hits = scored(trusted, anchor.phrase, stem=True, windows=True)
    if not hits:
        return None
    if anchor.direction == "day":
        # The day is a date one of the best matches states (a calendar entry states its own).
        for _score, record in hits[:3]:
            if record.source == "calendar":
                return record, record.event_time
            later = [moment for moment in stated_dates(record)
                     if moment.date() >= record.event_time.astimezone(LA).date()]
            if later:
                return record, min(later)
    record = hits[0][1]
    when = earliest.get(record.parent_id, record.event_time) if record.source == "meeting" else record.event_time
    return record, when


def stated_dates(record: Record) -> list[datetime]:
    """Dates written in the record body, in the record's year and time zone."""
    year = record.event_time.astimezone(LA).year
    found = []
    for match in _DATE.finditer(record.text):
        try:
            found.append(datetime(year, _MONTHS[match.group(1).lower()[:3]], int(match.group(2)), tzinfo=LA))
        except ValueError:
            continue
    for match in _ISO.finditer(record.text):
        try:
            found.append(datetime(int(match.group(1)), int(match.group(2)), int(match.group(3)), tzinfo=LA))
        except ValueError:
            continue
    return found


def rest_of_question(question: str, anchor: Anchor) -> str:
    """The question without the anchor phrase, so the second search is about the other thing."""
    lowered = question.replace(anchor.phrase, " ")
    return re.sub(r"\b(after|before|since|following|until|prior to|the day (?:after|before|of|i|we))\b", " ", lowered, flags=re.IGNORECASE)


def around(anchor: Anchor, record: Record, when: datetime, question: str, pool: list[Record]) -> list[tuple[float, Record]]:
    """Records on the asked side of the anchor that match the rest of the question, best first."""
    local = when.astimezone(LA)
    if anchor.direction == "day":
        day = (local + timedelta(days=anchor.offset_days)).date()
        inside = [other for other in pool if other.event_time.astimezone(LA).date() == day
                  or (other.source != "calendar" and any(moment.date() == day for moment in stated_dates(other)))]
    elif anchor.direction == "after":
        inside = [other for other in pool if when < other.event_time]
    else:
        inside = [other for other in pool if when - WINDOW <= other.event_time < when]
    inside = [other for other in inside if other.parent_id != record.parent_id and not is_untrusted(other)]
    if not inside:
        return []
    hits = scored(inside, rest_of_question(question, anchor), stem=True, windows=True)
    if anchor.direction == "day":
        matched = {other.id for _score, other in hits}
        calendar = [(0.0, other) for other in sorted(inside, key=lambda item: item.event_time)
                    if other.source == "calendar" and other.id not in matched]
        hits = hits + calendar
    return hits


def wrong_side(anchor: Anchor, record: Record, when: datetime, other: Record) -> bool:
    if anchor.direction == "after":
        return other.event_time < when and other.parent_id != record.parent_id
    if anchor.direction == "before":
        return other.event_time > when and other.parent_id != record.parent_id
    return False


def meeting_starts(records: list[Record]) -> dict[str, datetime]:
    starts: dict[str, datetime] = {}
    for record in records:
        if record.source != "meeting":
            continue
        current = starts.get(record.parent_id)
        if current is None or record.event_time < current:
            starts[record.parent_id] = record.event_time
    return starts


_OPEN_QUESTION = re.compile(
    r"\b(open|outstanding|pending|owe|owed|still (?:need|have|has|waiting|on)|haven'?t|hasn'?t|not yet"
    r"|to-?dos?|loose ends|waiting on|on my plate|follow(?:ing)? up on)\b",
    re.IGNORECASE,
)
_TASK = (
    r"(?:send|share|get|follow up|loop|set up|book|write|draft|put together|look into|check|ask|bring"
    r"|update|review|schedule|intro|introduce|forward|confirm|fix|finish|file|prepare|spin up)"
)
_PROMISE = re.compile(
    r"(?:\b(?:i'?ll|i will|i'?m going to|i can|let me|we'?ll|we will)|^\W*(?:will|gonna|going to))\s+(?:\w+\s+)?"
    + _TASK + r"\b",
    re.IGNORECASE,
)
_REQUEST = re.compile(
    r"\b(?:can you|could you|would you|please|need you to|mind)\s+(?:\w+\s+)?" + _TASK, re.IGNORECASE,
)
# Promises in a chat with an assistant, and offers in bulk mail, are not owed to anyone.
_NO_DEBT_SOURCES = {"chatgpt", "codex", "calendar"}
_ROLE_ADDRESS = re.compile(r"<(?:no-?reply|news|newsletter|info|hello|team|support|partners|notifications?|digest|marketing)@", re.IGNORECASE)
_DONE = re.compile(
    r"\b(sent|attached|shared|done|finished|shipped|booked|scheduled|set up|here'?s|here is|delivered|completed|closed)\b",
    re.IGNORECASE,
)
_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")


def _name(author: str | None) -> str:
    """'Jo Lee <jo@x.example>' and 'Jo Lee' are the same person."""
    return (author or "").split("<")[0].strip().lower()


def asks_open_items(question: str) -> bool:
    return _OPEN_QUESTION.search(question) is not None


@dataclass(frozen=True)
class Commitment:
    record: Record
    sentence: str
    debtor: str | None  # who owes it: the promiser, or the person asked


def commitments(pool: list[Record], owner: str) -> list[Commitment]:
    """Promises and requests stated in trusted records, one per record."""
    found = []
    first = owner.split()[0].lower()
    for record in pool:
        if is_untrusted(record) or record.source in _NO_DEBT_SOURCES or not record.author:
            continue
        if _ROLE_ADDRESS.search(record.author):
            continue
        for sentence in _SENTENCE.split(record.body or record.text):
            if re.search(r"\b(?:not|won'?t|can'?t|never)\b", sentence, re.IGNORECASE):
                continue
            if _PROMISE.search(sentence):
                found.append(Commitment(record, sentence, record.author))
                break
            if _REQUEST.search(sentence) and record.author != owner:
                # A request is the owner's to do only when it reaches the owner directly or by name.
                direct = len(record.participants) <= 2 or re.search(rf"\b{re.escape(first)}\b", sentence, re.IGNORECASE)
                found.append(Commitment(record, sentence, owner if direct else None))
                break
    return found


def completed(item: Commitment, pool: list[Record]) -> bool:
    """A later record by the debtor that names the same things and says it happened."""
    wanted = {token for token in analyze(item.sentence, stem=True) if token not in _STOP and len(token) >= 3}
    for other in pool:
        if other.event_time <= item.record.event_time or is_untrusted(other):
            continue
        if item.debtor and _name(other.author) != _name(item.debtor):
            continue
        if not _DONE.search(other.body or other.text):
            continue
        if len(wanted & tokens(other)) >= 2:
            return True
    return False


def open_items(question: str, pool: list[Record], owner: str) -> list[Record]:
    """Commitments with no later completion, those matching the question first, then newest first."""
    still_open = [item for item in commitments(pool, owner) if not completed(item, pool)]
    if re.search(r"\b(?:i|me|my)\b", question, re.IGNORECASE) and re.search(r"\bowe|\bi (?:still )?(?:need|have) to\b", question, re.IGNORECASE):
        still_open = [item for item in still_open if item.debtor == owner]
    if not still_open:
        return []
    by_id = {item.record.id: item.record for item in still_open}
    matched = [record for _score, record in scored(list(by_id.values()), question, stem=True, windows=True)]
    seen = {record.id for record in matched}
    rest = sorted((record for record in by_id.values() if record.id not in seen), key=lambda record: -record.event_time.timestamp())
    return matched + rest


_TOKENS: dict[tuple[str, str], frozenset[str]] = {}


def tokens(record: Record) -> frozenset[str]:
    # Keyed on the text too: an edited record keeps its id but not its words.
    key = (record.id, record.text)
    cached = _TOKENS.get(key)
    if cached is None:
        cached = frozenset(analyze(record.text, stem=True))
        _TOKENS[key] = cached
    return cached


def join_query(question: str, seeds: list[Record], pool: list[Record], limit: int = 6) -> str | None:
    """The question plus the rarest terms its best records share, for a second search."""
    frequency: Counter[str] = Counter()
    for record in pool:
        frequency.update(tokens(record))
    query = set(analyze(question, stem=True))
    counts: Counter[str] = Counter()
    for record in seeds:
        for token in tokens(record):
            if token in query or token in _STOP or len(token) < 3 or token.isdigit():
                continue
            counts[token] += 1
    # A term in two or more of the best records links them; a term in one record only is noise.
    shared = [token for token, count in counts.items() if count >= 2 and frequency[token] >= 2]
    shared.sort(key=lambda token: (frequency[token], -counts[token], token))
    if not shared:
        return None
    return question + " " + " ".join(shared[:limit])


def rrf(rankings: list[tuple[list[Record], float]], k: int = 60) -> list[tuple[float, Record]]:
    totals: dict[str, float] = {}
    seen: dict[str, Record] = {}
    for ranking, weight in rankings:
        for position, record in enumerate(ranking):
            totals[record.id] = totals.get(record.id, 0.0) + weight / (k + position + 1)
            seen.setdefault(record.id, record)
    return sorted(((score, seen[record_id]) for record_id, score in totals.items()), key=lambda item: -item[0])
