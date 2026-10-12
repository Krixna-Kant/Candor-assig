"""Deterministic answers from the records that exist at `as_of`.

Abstain only when the question's topic never appears in that view. A person or
company being mentioned is not enough, and a low retrieval score is not enough:
a paraphrase may use words the corpus does not.
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
    selected = _select(question, usable)
    if selected is None:
        return "I don't know.", [], True
    return _emit(*selected)


def _emit(text: str, sources: list[str]) -> tuple[str, list[str], bool]:
    return _limit(redact(text)), sources, False


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


def _kinds(question: str) -> dict[str, bool]:
    text = question.lower()
    return {
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
    if kind["status"] and re.search(r"\b(attached|posted|done|cancel|scratch)\b", sentence, re.IGNORECASE):
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
    """Pick one record's sentence, plus a second speaker's view of the same thing."""
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
            about_status = kind["status"] and record_overlap > 0 and bool(
                re.search(
                    r"\b(scratch|cancel|not yet|no longer|no need)\b",
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
            rows.append((score, rank, index, record, sentence, sentences, body))
    if not rows:
        return None
    rows.sort(key=lambda row: (-row[0], row[1], row[2]))
    chosen = rows[0]
    _score, _rank, index, record, sentence, sentences, body = chosen
    text = _with_speaker(body, _corrected(sentence))
    extra_sentences = 2 if kind["spoken"] or re.search(r"\band\b", question, re.IGNORECASE) else 1
    for follow in sentences[index + 1:index + 1 + extra_sentences]:
        text = f"{text} {follow}"
    sources = [record.id]
    other = _other_view(rows, record, text, question)
    if other is not None and not kind["temporal"] and re.search(r"\b(is|are|who)\b", question, re.IGNORECASE):
        extra, other_id = other
        text = f"{text} {extra}"
        if other_id not in sources:
            sources.append(other_id)
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


def _specific(sentence: str) -> bool:
    return bool(re.search(r"\d|Q[1-4]|\$|\bbecause\b", sentence, re.IGNORECASE))


def _other_view(rows: list[tuple], record: Record, text: str, question: str) -> tuple[str, str] | None:
    """A second person's sentence, only when it is about the same question."""
    best = rows[0][0]
    found: list[tuple[int, int, str, str]] = []
    for score, _rank, _index, other, sentence, _sentences, body in rows:
        if other.id == record.id:
            continue
        shared = _words(sentence) & _words(question)
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


def _corrected(sentence: str) -> str:
    """Keep the value stated after a spoken correction, not the number it replaced."""
    match = re.search(r"\b(?:sorry|misread|scratch that)\b", sentence, re.IGNORECASE)
    if not match:
        return sentence
    rest = sentence[match.end():].strip(" ,.-")
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


def _flatten(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _limit(text: str) -> str:
    words = text.split()
    if len(words) <= _WORD_CAP:
        return text
    return " ".join(words[:_WORD_CAP]).rstrip(",;:") + "."
