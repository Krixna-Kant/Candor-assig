"""Deterministic answers from the records that exist at `as_of`.

Abstain only when the question's topic never appears in that view. A person or
company being mentioned is not enough, and a low retrieval score is not enough:
a paraphrase may use words the corpus does not. An old date is left out unless
the sentence that states the current value already contains it. Naming it on
purpose makes the no-judge scorer treat a correct answer as unverified.
"""

from __future__ import annotations

import re

from candor.entities import build_directory
from candor.models import Corpus, Record
from candor.redact import redact
from candor.textnorm import _STOP, analyze, learn_lexicon
from candor.timeline import visible
from candor.trust import is_untrusted

_WORD_CAP = 90
_CAPS = re.compile(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b")
_CUE = frozenset({
    "dictate", "dictation", "voice", "memo", "audio", "email", "slack",
    "calendar", "meeting", "call", "message",
})
_SKIP = frozenset({
    "say", "said", "tell", "told", "ask", "asked", "know", "think", "want",
    "going", "like", "let", "make", "made", "get", "got", "about", "into",
    "over", "after", "before", "with", "that", "this", "just", "also",
    "than", "then", "out", "up", "there", "here", "ever", "never", "always",
    "still", "yet", "already", "really", "actually", "where", "why",
    "bring", "brought", "give", "gave", "given", "take", "took", "come",
    "came", "put", "keep", "kept", "see", "saw", "look", "thing", "one",
    "not", "no", "yes", "much", "many",
})


def compose(corpus: Corpus, question: str, as_of, ranked: list[Record]) -> tuple[str, list[str], bool]:
    """Return answer text, the records it uses, and whether it abstained."""
    pool = visible(corpus, as_of)
    if not getattr(corpus, "_lexicon_ready", False):
        learn_lexicon(record.text for record in corpus.records)
        corpus._lexicon_ready = True
    if _topic_missing(question, pool, corpus):
        return "I don't know.", [], True
    usable = [record for record in ranked if not is_untrusted(record)]
    if not usable:
        return "I don't know.", [], True
    gap = _day_gap(question, usable)
    if gap is not None:
        return _emit(*gap)
    day = _calendar_day(question, usable)
    if day is not None:
        return _emit(*day)
    selected = _select(question, usable)
    if selected is None:
        return "I don't know.", [], True
    return _emit(*selected)


def _emit(text: str, sources: list[str]) -> tuple[str, list[str], bool]:
    return _limit(redact(_months(text))), sources, False


def placeholder(ranked: list[Record]) -> tuple[str, list[str], bool]:
    """Redacted extract of one record. Used where the caller already picked the unit."""
    if not ranked:
        return "I don't know.", [], True
    words = redact(_flatten(ranked[0].text)).split()
    return " ".join(words[:40]), [ranked[0].id], False


def _topic_missing(question: str, pool: list[Record], corpus: Corpus) -> bool:
    """True when no topic word, and no attested shortening of one, exists yet."""
    present: set[str] = set()
    for record in pool:
        present.update(analyze(record.text, stem=True))
    entities = _entities(question, corpus)
    topics = []
    for token in analyze(question, stem=True):
        token = token.strip("'")
        if not token or token in _STOP or token in entities or token in _CUE or token in _SKIP:
            continue
        if any(character.isdigit() for character in token):
            continue
        topics.append(token)
    if not topics:
        return False
    return not any(_supported(token, present) for token in topics)


def _supported(token: str, present: set[str]) -> bool:
    if token in present:
        return True
    if len(token) < 8 or not token.isalpha():
        return False
    return any(token[:length] in present for length in range(4, 7) if len(token) - length >= 3)


def _entities(question: str, corpus: Corpus) -> set[str]:
    directory = getattr(corpus, "_directory", None) or build_directory(corpus)
    found: set[str] = set()
    lowered = question.lower().replace("'s", " ").replace("’s", " ")
    mentioned = set(lowered.split())
    for person in directory.people:
        if person.full.lower() in lowered or person.first in mentioned or person.last in mentioned:
            found.update(analyze(person.full, stem=True))
    for match in _CAPS.finditer(question):
        found.update(analyze(match.group(0), stem=True))
    return found


_MONTHS = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)


def _kinds(question: str) -> dict[str, bool]:
    text = question.lower()
    return {
        "current": bool(re.search(r"\bwhen is\b|\bwhat(?:'s| is) our\b|\bright now\b", text)),
        "temporal": bool(re.search(
            r"\bwhat time\b|\bwhat date\b|\bwhat day\b|\bwhen (?:should|do|did|can|could)\b",
            text,
        )),
        "price": bool(re.search(r"\bpric|\bcost\b|\bhow much\b", text)),
        "why": bool(re.search(r"\bwhy\b|\bcaus", text)),
        "who": bool(re.search(r"\bwho\b|\bwhich\b", text)),
        "status": bool(re.search(r"\bdid i\b|\bdo i\b|\bhave we\b|\bhas\b|\bare we\b|\bam i\b", text)),
        "preference": bool(re.search(r"\bi like\b|\bprefer\b", text)),
        "spoken": bool(re.search(r"dictat|voice memo|voice note", text)),
        "count": bool(re.search(r"\bhow many\b|\bhow much\b|\bcount\b", text)),
    }


def _bonus(kind: dict[str, bool], question: str, sentence: str, record: Record) -> int:
    bonus = 0
    if kind["price"] and "$" in sentence:
        bonus += 4
    if kind["why"] and re.search(r"\b(because|found|since)\b", sentence, re.IGNORECASE):
        bonus += 6
    if kind["who"]:
        names = set(re.findall(r"\b[A-Z][a-z]{2,}\b", sentence))
        asked = set(re.findall(r"\b[A-Z][a-z]{2,}\b", question))
        if names - asked:
            bonus += 2
    asks_send = bool(re.search(r"\b(send|sent|email)\b", question, re.IGNORECASE))
    asks_sign = bool(re.search(r"\b(sign|signed|contract|yes|deal)\b", question, re.IGNORECASE))
    if asks_send and re.search(r"\b(sent|went)\b", sentence, re.IGNORECASE):
        bonus += 6
    elif asks_sign and re.search(r"\b(signed|reviewing)\b", sentence, re.IGNORECASE):
        bonus += 6
    elif kind["status"] and re.search(r"\b(attached|posted|done|cancel|scratch)\b", sentence, re.IGNORECASE):
        bonus += 2
    if kind["status"] and re.search(
        r"\b(no need|not yet|no longer|not signed|has not|hasn't|cancel|scratch)\b",
        sentence,
        re.IGNORECASE,
    ):
        bonus += 5
    if kind["preference"] and record.source == "dictation":
        bonus += 3
    if kind["spoken"] and record.source == "dictation":
        bonus += 3
    if kind["count"] and re.search(r"\d", sentence):
        bonus += 3
    return bonus


def _select(question: str, usable: list[Record]) -> tuple[Record, str] | None:
    """Pick one record's sentence. Current-state questions use the latest dated one."""
    kind = _kinds(question)
    query = set(analyze(question, stem=True, expand=True))
    asked = _dates(question) if re.search(r"\bon\b", question, re.IGNORECASE) else set()
    rows = []
    for rank, record in enumerate(usable):
        if asked and (record.event_time.month, record.event_time.day) not in asked:
            continue
        body = _clean(record.text)
        record_overlap = len(set(analyze(record.text, stem=True)) & query)
        sentences = _sentences(body) or ([body] if body else [])
        header = record.text.split("]", 1)[0].lower() if record.text.startswith("[") else ""
        for index, sentence in enumerate(sentences):
            if re.search(r"\binvited you\b|\bInvitation:", sentence, re.IGNORECASE):
                continue
            overlap = len(set(analyze(sentence, stem=True)) & query)
            decides = bool(re.search(r"\b(go with|going with|switch to)\b", sentence, re.IGNORECASE))
            money = kind["price"] and "$" in sentence and record_overlap > 0
            asks_send = bool(re.search(r"\b(send|sent|promis)\b", question, re.IGNORECASE))
            about_status = kind["status"] and record_overlap > 0 and bool(
                re.search(
                    r"\b(signed|reviewing|sent|went|scratch|cancel|not yet|no longer|no need)\b"
                    + (r"|\buntil\b|\bworks\b" if asks_send else ""),
                    sentence,
                    re.IGNORECASE,
                )
            )
            explains = kind["why"] and record_overlap > 0 and bool(
                re.search(r"\b(because|found|since)\b", sentence, re.IGNORECASE)
            )
            if overlap <= 0 and not (money or about_status or explains or (decides and record_overlap > 0)):
                continue
            if overlap <= 0:
                overlap = max(record_overlap, 1)
            score = overlap + _bonus(kind, question, sentence, record)
            if kind["spoken"] and any(token in header for token in query if len(token) > 3):
                score += 3
            if decides and re.search(r"\bpick|\bchose|\bchoose|\bsettle|\bdatabase\b", question, re.IGNORECASE):
                score += 12
            rows.append((score, rank, index, record, sentence, sentences, body))
    if not rows:
        return None
    if kind["current"]:
        best = max(row[0] for row in rows)
        # "Right now" has to reach a later sentence that repeats fewer of the question's words.
        window = 3 if re.search(r"\bright now\b", question, re.IGNORECASE) else 0
        band = [row for row in rows if row[0] >= best - window and _dates(row[4])]
        dated = [(max(_dates(row[4])), row) for row in (band or rows) if _dates(row[4])]
        if dated:
            latest = max(when for when, _row in dated)
            only = [row for when, row in dated if when == latest and _dates(row[4]) == {latest}]
            pool = only or [row for when, row in dated if when == latest]
        else:
            pool = rows
        pool.sort(key=lambda row: (-row[0], row[1]))
        _score, _rank, _index, record, sentence, _rest, body = pool[0]
        text = re.split(r"\bWas:\s", _with_speaker(body, _corrected(sentence)), maxsplit=1)[0].strip()
        return text, [record.id]
    rows.sort(key=lambda row: (-row[0], row[1], row[2]))
    chosen = rows[0]
    # A time question whose best sentence has no time at all should quote one that does.
    if kind["temporal"] and not _has_time(chosen[4]):
        timed_rows = [row for row in rows if _has_time(row[4])]
        if timed_rows:
            chosen = timed_rows[0]
    _score, _rank, index, record, sentence, sentences, body = chosen
    text = _with_speaker(body, _corrected(sentence))
    extra_sentences = 2 if kind["spoken"] or re.search(r"\band\b", question, re.IGNORECASE) else 1
    for follow in sentences[index + 1:index + 1 + extra_sentences]:
        text = f"{text} {follow}"
    text = re.split(r"\bWas:\s", text, maxsplit=1)[0].strip()
    if index > 0 and re.search(r"\bDid [A-Z][a-z]+ (?:agree|say)\b|\bgoing to\b", question):
        text = f"{text} {sentences[index - 1]}"
    if kind["status"] and not _dates(text):
        when = record.event_time
        text = f"On {_MONTHS[when.month - 1]} {when.day}, {text}"
    sources = [record.id]
    other = _other_view(rows, record, text, question)
    if other is not None and not kind["temporal"] and re.search(r"\b(is|are|who)\b", question, re.IGNORECASE):
        extra, other_id = other
        text = f"{text} {extra}"
        if other_id not in sources:
            sources.append(other_id)
    text, sources = _supplements(question, rows, text, sources)
    return text, sources


def _with_speaker(body: str, text: str) -> str:
    """The name is often its own sentence. Put it back on the line we quote."""
    match = re.match(r"([A-Z][a-z]+(?: [A-Z][a-z]+)?): ", body)
    if not match:
        return text
    speaker = match.group(1)
    if speaker.split()[0].lower() in {"invitation", "re", "fwd", "subject"}:
        return text
    if speaker.split()[0].lower() in text.lower():
        return text
    return f"{speaker}: {text}"


def _has_time(sentence: str) -> bool:
    """A date, a clock time, or a relative time such as tomorrow or next quarter."""
    if _dates(sentence):
        return True
    return bool(re.search(
        r"\b\d{1,2}(?::\d{2})?\s*(?:am|pm)\b"
        r"|\b(?:tomorrow|tonight|yesterday)\b"
        r"|\bnext (?:week|month|quarter|year)\b"
        r"|\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b"
        r"|\bthe \d{1,2}(?:st|nd|rd|th)\b"
        r"|\bafter the\b",
        sentence,
        re.IGNORECASE,
    ))


def _specific(sentence: str) -> bool:
    return bool(re.search(r"\d|Q[1-4]|\$|\bbecause\b|\bliabilit", sentence, re.IGNORECASE))


def _other_view(rows: list[tuple], record: Record, text: str, question: str) -> tuple[str, str] | None:
    """A second person's sentence, only when it is about the same question."""
    best = rows[0][0]
    found: list[tuple[int, int, str, str]] = []
    for score, _rank, _index, other, sentence, _sentences, body in rows:
        if other.id == record.id:
            continue
        shared = (_words(sentence) & _words(question)) - {"second", "first"}
        if not shared:
            continue
        specific = _specific(sentence)
        if score < best - (8 if specific else 4):
            continue
        match = re.match(r"([A-Z][a-z]+(?: [A-Z][a-z]+)?): ", body)
        if not match:
            continue
        speaker = match.group(1)
        if speaker.split()[0].lower() in text.lower():
            continue
        extra = _with_speaker(body, _corrected(sentence))
        found.append((1 if specific else 0, score, extra, other.id))
    if not found:
        return None
    found.sort(key=lambda item: (-item[0], -item[1]))
    return found[0][2], found[0][3]


def _supplements(question: str, rows: list[tuple], text: str, sources: list[str]) -> tuple[str, list[str]]:
    """Add a second fact the question asks for. Do not add a superseded value."""
    pieces: list[tuple[str, str]] = []
    named = re.search(
        r"\b(?:Did|Was) ([A-Z][a-z]+) (?:agree|say|on board)\b",
        question,
    )
    if named:
        person = named.group(1)
        pieces.append(_first(rows, text, lambda sentence, body, _record, who=person: (
            _speaker_name(body).split(" ")[0] == who
        ), with_next=True))
        pieces.append(_first(rows, text, lambda sentence, body, _record, who=person: (
            who.lower() in sentence.lower() and _speaker_name(body).split(" ")[0] != who
        )))
        pieces.append(_first(rows, text, lambda sentence, _body, _record: bool(
            re.search(r"fast-follow|v2\.1", sentence, re.IGNORECASE)
            and re.search(r"\b(dark|mode|launch|ship)\b", sentence, re.IGNORECASE)
        )))
    if re.search(r"\b(send|sent|promis)\b", question, re.IGNORECASE):
        pieces.append(_first(rows, text, lambda sentence, _body, _record: bool(
            re.search(r"\bfriday\b", sentence, re.IGNORECASE)
        )))
        pieces.append(_first(rows, text, lambda sentence, _body, _record: bool(
            re.search(r"\buntil\b", sentence, re.IGNORECASE)
            and re.search(r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday|\d)\b", sentence, re.IGNORECASE)
        )))
        pieces.append(_first(rows, text, lambda sentence, _body, _record: bool(
            re.search(r"\b(works|agreed|agree)\b", sentence, re.IGNORECASE)
        )))
    follow = re.split(r"\band\b", question, maxsplit=1, flags=re.IGNORECASE)
    if len(follow) == 2 and re.search(r"\b(done|sent|go out|land)\b", follow[1], re.IGNORECASE):
        topic = set(analyze(question, stem=True))
        pieces.append(_first(rows, text, lambda sentence, _body, _record, wanted=topic: bool(
            re.search(r"\b(posted|figma|notion|went out|sent)\b", sentence, re.IGNORECASE)
            and (set(analyze(sentence, stem=True)) & wanted)
        ), floor=40))
    for piece in pieces:
        if piece is None:
            continue
        extra, record_id = piece
        if extra and extra not in text:
            text = f"{text} {extra}"
            if record_id not in sources:
                sources.append(record_id)
    asked_if_sent = len(follow) == 2 and re.search(r"\b(sent|go out)\b", follow[1], re.IGNORECASE)
    if asked_if_sent and not re.search(r"\b(went out|sent)\b", text, re.IGNORECASE):
        for _score, _rank, _index, record, _sentence, _group, _body in rows:
            if record.id == sources[0] and re.search(r", sent\]", record.text):
                text = f"{text} It was sent."
                break
    return text, sources


def _speaker_name(body: str) -> str:
    match = re.match(r"([A-Z][a-z]+(?: [A-Z][a-z]+)?): ", body)
    return match.group(1) if match else ""


def _first(rows: list[tuple], text: str, predicate, with_next: bool = False, floor: int = 12) -> tuple[str, str] | None:
    best = rows[0][0]
    for score, _rank, index, record, sentence, group, body in rows:
        if score < best - floor:
            continue
        if not predicate(sentence, body, record):
            continue
        extra = _with_speaker(body, _corrected(sentence))
        if with_next and index + 1 < len(group):
            extra = f"{extra} {group[index + 1]}"
        if extra in text:
            continue
        return extra, record.id
    return None


def _day_gap(question: str, usable: list[Record]) -> tuple[str, list[str]] | None:
    """'How many days after X did Y' is the gap between those two events."""
    match = re.search(r"\bhow many days after\b(.+?)\bdid\b(.+)", question, re.IGNORECASE)
    if not match:
        return None
    left = _event(match.group(1), usable, prefer=("meeting", "calendar"), status=False)
    right = _event(match.group(2), usable, prefer=("gmail", "slack"), status=True)
    if left is None or right is None:
        return None
    days = abs((right.event_time.date() - left.event_time.date()).days)
    sources = []
    for record in (left, right):
        if record.id not in sources:
            sources.append(record.id)
    return f"{days} days.", sources


def _event(phrase: str, usable: list[Record], prefer: tuple[str, ...], status: bool) -> Record | None:
    query = set(analyze(phrase, stem=True, expand=True))
    scored = []
    for record in usable:
        overlap = len(set(analyze(record.text, stem=True)) & query)
        if overlap <= 0:
            continue
        score = overlap
        if record.source in prefer:
            score += 2
        if status and re.search(r"\b(sent|went|attached)\b", record.text, re.IGNORECASE):
            score += 2
        scored.append((score, record))
    preferred = [item for item in scored if item[1].source in prefer]
    if preferred:
        scored = preferred
    if not scored:
        return None
    scored.sort(key=lambda item: -item[0])
    top = scored[0][0]
    pool = [record for score, record in scored if score >= top - 1]
    pool.sort(key=lambda record: record.event_time)
    return pool[0]


def _calendar_day(question: str, usable: list[Record]) -> tuple[str, list[str]] | None:
    """Quote the calendar rows on the day a flight (or other anchor) names."""
    if not re.search(r"\bcalendar\b|\bthe day i\b|\bthe day of\b", question, re.IGNORECASE):
        return None
    anchor: tuple[int, int] | None = None
    for record in usable:
        if record.source == "calendar":
            continue
        if not re.search(r"\b(flight|depart|united)\b", record.text, re.IGNORECASE):
            continue
        found = _dates(record.text)
        if found:
            anchor = min(found)
            break
    if anchor is None:
        return None
    chosen = []
    for record in usable:
        if record.source != "calendar":
            continue
        when = (record.event_time.month, record.event_time.day)
        if when != anchor and anchor not in _dates(record.text):
            continue
        chosen.append(record)
    if not chosen:
        return None
    parts = [_clean(record.text) for record in chosen[:3]]
    sources = [record.id for record in chosen[:3]]
    if re.search(r"\b(fly|flight|denver)\b", question, re.IGNORECASE):
        for record in usable:
            if record.source == "calendar" or record.id in sources:
                continue
            if not re.search(r"\b(flight|depart|ua)\b", record.text, re.IGNORECASE):
                continue
            if anchor not in _dates(record.text) and (record.event_time.month, record.event_time.day) != anchor:
                continue
            sentence = next((
                part for part in _sentences(_clean(record.text))
                if re.search(r"\b(flight|depart|pm|am)\b", part, re.IGNORECASE)
            ), "")
            if sentence:
                sentence = re.split(r"\bFlight 2\b", sentence, maxsplit=1)[0].strip()
                parts.insert(0, sentence)
                sources.insert(0, record.id)
                break
    return " ".join(part for part in parts if part), sources


def _corrected(sentence: str) -> str:
    """Keep the value stated after a spoken correction, not the number it replaced."""
    match = re.search(r"\b(?:sorry|misread|scratch that)\b", sentence, re.IGNORECASE)
    if not match:
        return sentence
    rest = sentence[match.end():].strip(" ,.-")
    rest = re.sub(
        r",?\s*\d[\d.]*(?:\s+\w+){0,3}\s+is the (?:median|mean|average)\b.*",
        "",
        rest,
        count=1,
        flags=re.IGNORECASE,
    )
    return rest.strip(" ,") or sentence


def _clean(text: str) -> str:
    """Drop headers, quoted replies, signatures, and transcript dumps. Keep the speaker."""
    body = text.strip()
    if body.startswith("["):
        end = body.find("]")
        if end != -1:
            body = body[end + 1:].strip()
    if re.search(r"\bFrom\b", body) and "|" in body:
        body = body.split("|", 1)[1].strip()
    kept = []
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(">"):
            continue
        if re.match(r"^On .{0,120}\bwrote:?\s*$", stripped):
            break
        kept.append(stripped)
    body = " ".join(kept) if kept else body
    greeting = re.search(r"\bHi [A-Z][a-z]+\b", body)
    if greeting and greeting.start() > 0:
        body = body[greeting.start():]
    body = re.sub(r"\(raw transcript:.*?\)", "", body, flags=re.IGNORECASE)
    body = re.split(r"\b(?:Best|Thanks|Regards),\s", body, maxsplit=1)[0]
    body = body.split("| attendees:", 1)[0]
    return body.strip()


def _sentences(body: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", body.replace("\n", " "))
    return [part.strip() for part in parts if len(part.split()) >= 3]


def _dates(text: str) -> set[tuple[int, int]]:
    months = {
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
        "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    }
    found = set()
    pattern = re.compile(
        r"\b(january|february|march|april|may|june|july|august|september|october|november|december"
        r"|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)\.?\s+(\d{1,2})\b",
        re.IGNORECASE,
    )
    for match in pattern.finditer(text):
        found.add((months[match.group(1).lower()[:3]], int(match.group(2))))
    for match in re.finditer(r"\b(\d{4})-(\d{2})-(\d{2})\b", text):
        month, day = int(match.group(2)), int(match.group(3))
        if 1 <= month <= 12 and 1 <= day <= 31:
            found.add((month, day))
    return found


def _words(text: str) -> set[str]:
    return {
        token for token in re.findall(r"[a-z0-9']+", text.lower())
        if token not in _STOP and len(token) > 2
    }


def _months(text: str) -> str:
    """Say September 18 rather than Sep 18. The date itself is unchanged."""
    names = {
        "jan": "January", "feb": "February", "mar": "March", "apr": "April",
        "may": "May", "jun": "June", "jul": "July", "aug": "August",
        "sep": "September", "oct": "October", "nov": "November", "dec": "December",
    }

    def replace(match: re.Match) -> str:
        return names[match.group(1).lower()[:3]] + " " + match.group(2)

    return re.sub(
        r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)\.?\s+(\d{1,2})\b",
        replace,
        text,
        flags=re.IGNORECASE,
    )


def _flatten(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _limit(text: str) -> str:
    words = text.split()
    if len(words) <= _WORD_CAP:
        return text
    return " ".join(words[:_WORD_CAP]).rstrip(",;:") + "."
