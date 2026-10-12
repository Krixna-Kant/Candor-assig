"""Time filter, then BM25, entities, chains, and a per-parent cap.

`chain_width` is how many extra records a seed may pull in: same-channel
neighbors within three days, and same-thread mail.
The cap stops one meeting from filling the top of the list.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta

from candor.bm25 import rank, scored
from candor.entities import Directory, build_directory
from candor.hops import (
    around, asks_open_items, find_anchor, join_query, meeting_starts, open_items, resolve, rrf, wrong_side,
)
from candor.ingest import ALEX_NAME
from candor.models import Corpus, Record
from candor.textnorm import analyze, learn_lexicon
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
JOIN_WEIGHT = 0.5
_STATUS = re.compile(r"^\s*(has|have|is|are|did|does|do)\b|\b(yet|still|so far|status)\b", re.IGNORECASE)


def retrieve(
    corpus: Corpus,
    question: str,
    as_of: datetime,
    *,
    stem: bool,
    limit: int = 20,
    chain_width: int = 3,
    parent_cap: int = 3,
    trace: dict | None = None,
) -> list[Record]:
    """Best-first units that exist at `as_of`. Plain mode is BM25 only.

    `trace`, when given, is filled with what each hop did, for `explain`.
    """
    trace = {} if trace is None else trace
    pool = visible(corpus, as_of)
    _ensure_lexicon(corpus)
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
    lexical = sorted(adjusted, key=lambda item: -item[0])
    top_score = lexical[0][0] if lexical else 1.0
    added: set[str] = set()
    cued = _cued(pool, question, top_score)
    adjusted.extend(cued)
    adjusted, anchored = _anchored(question, pool, adjusted, top_score, chain_width)
    pending = _pending(question, pool, top_score, chain_width)
    adjusted.extend(pending)
    added.update(record.id for _score, record in cued + anchored + pending)
    anchor = find_anchor(question)
    if anchor and anchored:
        trace["anchor"] = (anchor.phrase, anchor.direction, anchored[0][1].id, [record.id for _s, record in anchored[1:]])
    if pending:
        trace["open_items"] = [record.id for _score, record in pending]
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
    neighbors = _neighbors(seeds, pool, query_terms, chain_width, question)
    adjusted.extend(neighbors)
    added.update(record.id for _score, record in neighbors)
    if kind == "calendar" or _asks_about_a_day(question):
        on_day = _calendar_on_day(question, pool, adjusted, chain_width)
        adjusted.extend(on_day)
        added.update(record.id for _score, record in on_day)
    adjusted.sort(key=lambda item: -item[0])
    return _joined(question, pool, adjusted, added, directory, parent_cap, limit, trace)


def _joined(question, pool, adjusted, added, directory, parent_cap, limit, trace) -> list[Record]:
    """Search again with the terms the best records share, and merge the two rankings by rank.

    A record a hop added (anchor, thread, calendar day) was not found by words, so the second
    search cannot judge it; it keeps its first-ranking place in the second ranking too.
    """
    direct = _cap(adjusted, parent_cap, max(limit, 40))
    query = join_query(question, [record for record in _cap(adjusted, 1, 5) if not is_untrusted(record)], pool)
    if query is None:
        return direct[:limit]
    trace["join_terms"] = query[len(question):].split()
    second = [
        (_adjust(score, record, question, directory), record)
        for score, record in scored(pool, query, stem=True, windows=True)
    ]
    second.sort(key=lambda item: -item[0])
    again = [record for record in _cap(second, parent_cap, 40) if record.id not in added]
    for position, record in enumerate(direct):
        if record.id in added:
            again.insert(min(position, len(again)), record)
    merged = rrf([(direct, 1.0), (again, JOIN_WEIGHT)])
    return _cap(merged, parent_cap, limit)


def _asks_status(question: str) -> bool:
    return bool(_STATUS.search(question))


def _ensure_lexicon(corpus: Corpus) -> None:
    if getattr(corpus, "_lexicon_ready", False):
        return
    learn_lexicon(record.text for record in corpus.records)
    corpus._lexicon_ready = True


def _asks_about_a_day(question: str) -> bool:
    """A day defined by another event, not only a question that says 'calendar'."""
    return re.search(r"\bday of\b|\bthe day i\b", question, re.IGNORECASE) is not None


_SPOKEN = re.compile(r"dictat|voice memo|voice note|audio note", re.IGNORECASE)


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
    if _SPOKEN.search(lowered) and record.source == "dictation":
        factor *= 4.0
    if re.search(r"\bemail", lowered) and record.source == "gmail":
        factor *= 1.6
    if re.search(r"\bslack\b", lowered) and record.source == "slack":
        factor *= 1.8
    asked = _dates(question)
    if asked and (record.event_time.month, record.event_time.day) in asked:
        factor *= 3.0
    return factor


def _anchored(question, pool, adjusted, top_score, chain_width):
    """'After X' or 'the day of X': find X, then rank what sits on the asked side of it."""
    anchor = find_anchor(question)
    if anchor is None:
        return adjusted, []
    resolved = resolve(anchor, pool, meeting_starts(pool))
    if resolved is None:
        return adjusted, []
    record, when = resolved
    kept = [(score * (0.6 if wrong_side(anchor, record, when, other) else 1.0), other) for score, other in adjusted]
    added = [(top_score * 0.9, record)]
    for index, (_score, other) in enumerate(around(anchor, record, when, question, pool)[:chain_width]):
        added.append((top_score * (0.7 - 0.01 * index), other))
    return kept + added, added


def _pending(question, pool, top_score, chain_width) -> list[tuple[float, Record]]:
    """'What do I still owe': requests and promises that no later record completes."""
    if not asks_open_items(question):
        return []
    found = open_items(question, pool, ALEX_NAME)
    return [(top_score * (0.85 - 0.01 * index), record) for index, record in enumerate(found[: chain_width + 3])]


def _cued(pool: list[Record], question: str, top_score: float) -> list[tuple[float, Record]]:
    """A source the question names may not share words with the question."""
    if not _SPOKEN.search(question):
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
        newest = None
        if seed.source == "gmail" and candidates and candidates[0][1] > seed.event_time and _asks_status(question):
            newest = candidates[0][2].id
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
            # The newest message in a thread is its current state, which is what a status question asks.
            forced.append((score * (1.01 if other.id == newest else weight), other))
            picked += 1
            if picked >= chain_width:
                break
    return forced


def _calendar_on_day(question: str, pool: list[Record], ranked: list[tuple[float, Record]], chain_width: int) -> list[tuple[float, Record]]:
    """Events whose start falls on a date the question names."""
    dates = set(_dates(question))
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
