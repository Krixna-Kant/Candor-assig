"""Time filter, then BM25, entities, chains, and a per-parent cap.

`chain_width` is how many extra records a seed may pull in: later mentions of
the same terms, same-channel neighbors within three days, and same-thread mail.
The cap stops one meeting from filling the top of the list.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta

from candor.bm25 import rank, scored
from candor.entities import Directory, build_directory
from candor.models import Corpus, Record
from candor.textnorm import analyze
from candor.timeline import visible
from candor.trust import is_untrusted, question_is_about_untrusted

_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}
_MONTHS.update({name[:3]: number for name, number in list(_MONTHS.items())})
_DATE = re.compile(
    r"\b(january|february|march|april|may|june|july|august|september|october|november|december"
    r"|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)\.?\s+(\d{1,2})\b",
    re.IGNORECASE,
)
_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")


def retrieve(
    corpus: Corpus,
    question: str,
    as_of: datetime,
    *,
    stem: bool,
    limit: int = 20,
    chain_width: int = 3,
    parent_cap: int = 3,
) -> list[Record]:
    """Best-first units that exist at `as_of`. Plain mode is BM25 only."""
    pool = visible(corpus, as_of)
    if not stem:
        return rank(pool, question, stem=False, limit=limit)
    base = scored(pool, question, stem=True, windows=True)
    if not base:
        return []
    directory = _directory(corpus)
    kind = _kind(question)
    query_terms = set(analyze(question, stem=True))
    adjusted = [
        (_adjust(score, record, question, directory), record)
        for score, record in base
    ]
    if kind == "current":
        adjusted = _prefer_later_dated(adjusted, pool)
    lexical = sorted(adjusted, key=lambda item: -item[0])
    top_score = lexical[0][0] if lexical else 1.0
    if kind == "current":
        adjusted.extend(_latest(pool, query_terms, chain_width, top_score, question))
    adjusted.extend(_cued(pool, question, top_score))
    best: dict[str, tuple[float, Record]] = {}
    for score, record in adjusted:
        current = best.get(record.id)
        if current is None or score > current[0]:
            best[record.id] = (score, record)
    lexical = sorted(best.values(), key=lambda item: -item[0])
    # Cap before expansion so one meeting cannot crowd out the email a thread hangs from.
    diverse = _cap(lexical, parent_cap, max(limit, 40))
    score_of = {record.id: score for score, record in lexical}
    seeds = [(score_of[record.id], record) for record in diverse[:5]]
    # An email can sit just outside the top and still be the start of the thread that answers it.
    seeds.extend((score_of[record.id], record) for record in diverse if record.source == "gmail")
    adjusted.extend(_neighbors(seeds, pool, query_terms, chain_width, question))
    if kind == "calendar":
        adjusted.extend(_calendar_on_day(question, pool, adjusted, chain_width))
    adjusted.sort(key=lambda item: -item[0])
    return _cap(adjusted, parent_cap, limit)


def _directory(corpus: Corpus) -> Directory:
    cached = getattr(corpus, "_directory", None)
    if cached is None:
        cached = build_directory(corpus)
        corpus._directory = cached
    return cached


def _kind(question: str) -> str:
    lowered = question.lower()
    if lowered.startswith("why") or "why did" in lowered:
        return "cause"
    if "calendar" in lowered:
        return "calendar"
    if re.search(r"\b(when is|what is our|what's our|do i still|has |have we)\b", lowered):
        return "current"
    return "general"


def _adjust(score: float, record: Record, question: str, directory: Directory) -> float:
    score *= _entity_factor(record, directory.resolve_question(question), directory)
    score *= _source_factor(question, record)
    if is_untrusted(record) and not question_is_about_untrusted(question):
        score *= 0.02
    return score


def _entity_factor(record: Record, resolution, directory: Directory) -> float:
    if not resolution.wanted and not resolution.blocked:
        return 1.0
    keys = directory.keys_for(record)
    if keys & set(resolution.blocked) and not (keys & set(resolution.wanted)):
        return 0.25
    if keys & set(resolution.wanted):
        return 1.45
    return 1.0


def _source_factor(question: str, record: Record) -> float:
    lowered = question.lower()
    factor = 1.0
    if re.search(r"dictat", lowered) and record.source == "dictation":
        factor *= 4.0
    if re.search(r"\bemail", lowered) and record.source == "gmail":
        factor *= 1.6
    if re.search(r"\bslack\b", lowered) and record.source == "slack":
        factor *= 1.8
    asked = _dates(question)
    if asked and (record.event_time.month, record.event_time.day) in asked:
        factor *= 3.0
    return factor


def _prefer_later_dated(rows: list[tuple[float, Record]], pool: list[Record]) -> list[tuple[float, Record]]:
    """A 'when is' question wants the later statement that actually names a date.

    The delivery timestamp on every unit is ignored. Only a date written in the body counts,
    so 'launch week' does not beat 'October 21'.
    """
    times = [record.available_at for record in pool]
    earliest, latest = min(times), max(times)
    span = max((latest - earliest).total_seconds(), 1.0)
    rescored = []
    for score, record in rows:
        position = (record.available_at - earliest).total_seconds() / span
        factor = 0.75 + 0.7 * position
        if _DATE.search(record.body or "") or _ISO.search(record.body or ""):
            factor *= 1.35
        rescored.append((score * factor, record))
    return rescored


def _latest(pool: list[Record], query_terms: set[str], chain_width: int, top_score: float, question: str) -> list[tuple[float, Record]]:
    """Current-state slot: the latest units that contain the rarest query term."""
    if chain_width <= 0 or not query_terms:
        return []
    tokenized = [(record, set(analyze(record.text, stem=True))) for record in pool]
    frequency: Counter[str] = Counter()
    for _record, tokens in tokenized:
        frequency.update(tokens)
    useful = [term for term in query_terms if frequency[term]]
    if not useful:
        return []
    rarest = min(useful, key=lambda term: (frequency[term], term))
    hits = []
    for record, tokens in tokenized:
        if rarest not in tokens:
            continue
        if frequency[rarest] > 25 and len(tokens & query_terms) < 2:
            continue
        if is_untrusted(record) and not question_is_about_untrusted(question):
            continue
        hits.append(record)
    hits.sort(key=lambda record: record.available_at, reverse=True)
    return [(top_score * (0.7 - 0.02 * offset), record) for offset, record in enumerate(hits[:chain_width])]


def _cued(pool: list[Record], question: str, top_score: float) -> list[tuple[float, Record]]:
    """A source the question names may not share words with the question."""
    if not re.search(r"dictat", question, re.IGNORECASE):
        return []
    dates = set(_dates(question))
    picked = []
    for record in pool:
        if record.source != "dictation":
            continue
        if dates and (record.event_time.month, record.event_time.day) not in dates:
            continue
        picked.append(record)
    picked.sort(key=lambda record: record.event_time)
    return [(top_score * 0.85, record) for record in picked[:6]]


def _neighbors(
    seeds: list[tuple[float, Record]],
    pool: list[Record],
    query_terms: set[str],
    chain_width: int,
    question: str,
) -> list[tuple[float, Record]]:
    """Follow a short chain: a meeting mention, then the Slack thread around it, or one email thread.

    Width 1 keeps the nearest later step. Width 3 keeps the current state, the change, and the origin.
    """
    if chain_width <= 0:
        return []
    by_channel: dict[str, list[Record]] = defaultdict(list)
    by_thread: dict[str, list[Record]] = defaultdict(list)
    for record in pool:
        if record.source == "slack" and record.channel:
            by_channel[record.channel].append(record)
        if record.thread_id and record.source == "gmail":
            by_thread[record.thread_id].append(record)
    # Thread mates may already be weak hits. Let the stronger message in the thread lift them.
    seen = {record.id for _score, record in seeds if record.source != "gmail"}
    first = _expand(seeds, by_channel, by_thread, query_terms, chain_width, seen, question, hop=1)
    second = _expand(first, by_channel, by_thread, query_terms, chain_width, seen, question, hop=2)
    return first + second


def _expand(seeds, by_channel, by_thread, query_terms, chain_width, seen, question, hop: int) -> list[tuple[float, Record]]:
    forced = []
    for score, seed in seeds:
        candidates: list[tuple[float, datetime, Record]] = []
        if seed.source == "slack" and seed.channel and hop == 2:
            for other in by_channel[seed.channel]:
                delta = abs(other.event_time - seed.event_time)
                if delta <= timedelta(hours=6):
                    candidates.append((delta.total_seconds(), other.event_time, other))
        if seed.source == "meeting" and hop == 1:
            seed_terms = set(analyze(seed.text, stem=True))
            for rows in by_channel.values():
                for other in rows:
                    if abs(other.event_time - seed.event_time) > timedelta(days=3):
                        continue
                    other_terms = set(analyze(other.text, stem=True))
                    if (other_terms & seed_terms) and (other_terms & query_terms):
                        candidates.append((0.0, other.event_time, other))
        if seed.source == "gmail" and seed.thread_id and hop == 1:
            for other in by_thread[seed.thread_id]:
                candidates.append((0.0, other.event_time, other))
        candidates.sort(key=lambda item: (item[0], -item[1].timestamp()))
        picked = 0
        # A reply in the same thread is the same conversation, so it keeps the seed's rank.
        # A Slack neighbor is only a candidate and sits lower.
        if hop == 1 and seed.source == "gmail":
            weight = 0.98
        elif hop == 1:
            weight = 0.72
        else:
            weight = 0.6
        for _delta, _when, other in candidates:
            if other.id in seen:
                continue
            if is_untrusted(other) and not question_is_about_untrusted(question):
                continue
            seen.add(other.id)
            forced.append((score * weight, other))
            picked += 1
            if picked >= chain_width:
                break
    return forced


def _calendar_on_day(question: str, pool: list[Record], ranked: list[tuple[float, Record]], chain_width: int) -> list[tuple[float, Record]]:
    """Events whose start falls on a date the question names, or on a travel day in evidence."""
    dates = set(_dates(question))
    lowered = question.lower()
    if not dates and re.search(r"fly|flight|travel", lowered):
        for _score, record in ranked[:40]:
            if record.source == "calendar":
                continue
            text = record.text.lower()
            if "flight" in text or "united" in text or "depart" in text:
                dates.update(_dates(record.text))
                if dates:
                    break
    if not dates:
        return []
    top = ranked[0][0] if ranked else 1.0
    found = []
    for record in pool:
        if record.source != "calendar":
            continue
        if (record.event_time.month, record.event_time.day) in dates:
            found.append(record)
    found.sort(key=lambda record: record.event_time)
    return [(top * (0.95 - 0.01 * index), record) for index, record in enumerate(found[: max(chain_width, 1) + 3])]


def _dates(text: str) -> list[tuple[int, int]]:
    found = []
    for match in _DATE.finditer(text):
        month = _MONTHS[match.group(1).lower()[:3]]
        found.append((month, int(match.group(2))))
    for match in _ISO.finditer(text):
        found.append((int(match.group(2)), int(match.group(3))))
    return found


def _cap(scored_rows: list[tuple[float, Record]], parent_cap: int, limit: int) -> list[Record]:
    kept: list[Record] = []
    seen: set[str] = set()
    counts: Counter[str] = Counter()
    for _score, record in scored_rows:
        if record.id in seen:
            continue
        if counts[record.parent_id] >= parent_cap:
            continue
        seen.add(record.id)
        counts[record.parent_id] += 1
        kept.append(record)
        if len(kept) >= limit:
            break
    return kept
