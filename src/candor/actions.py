"""Turn a command into the actions it would take. Nothing is sent.

People, channels, and event times come from the records visible at `as_of`.
A shared first name is resolved only when one person owns the topic; otherwise
the plan asks which person. A destructive command asks for confirmation.
Text planted in the corpus is content: an address that appears only there is
never a recipient, and a command that carries an instruction is not obeyed.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from candor.entities import Directory, Person, build_directory
from candor.ingest import default_data_dir
from candor.models import Corpus, Record
from candor.redact import redact
from candor.slots import names_a_thing, rewrite
from candor.timeline import visible
from candor.trust import is_untrusted

LA = ZoneInfo("America/Los_Angeles")

_INJECTION = re.compile(
    r"ignore (?:all |your |previous )?instructions|note to any .{0,40}assistant|<!--",
    re.IGNORECASE,
)
_EMAIL = re.compile(r"[a-z0-9._+-]+@[a-z0-9.-]+\.[a-z]{2,}")
_IMPERATIVE = re.compile(
    r"\b(message|email|remind|book|schedule|move|reschedule|open|tell|thank|"
    r"delete|erase|wipe|cancel|slack|text|ping|forward|send|remove)\b",
    re.IGNORECASE,
)
_SPLIT_VERB = re.compile(
    r"^(email|message|thank|tell|remind|book|schedule|move|reschedule|open|"
    r"slack|text|ping|forward|send|delete|erase|wipe)\b",
    re.IGNORECASE,
)
_DESTRUCTIVE = re.compile(
    r"\b(delete|erase|wipe|destroy|cancel|remove|drop all)\b",
    re.IGNORECASE,
)
_QUESTION = re.compile(
    r"^(what|when|who|why|how|where|is|are|did|do|does|has|have|can|could)\b",
    re.IGNORECASE,
)
_NOT_A_NAME = frozenset({"the", "a", "an", "and", "or"})
_GLUE = frozenset({
    "message", "email", "slack", "tell", "thank", "thanks", "remind", "book",
    "schedule", "move", "reschedule", "open", "channel", "about", "with",
    "from", "that", "this", "please", "tomorrow", "minutes", "minute", "hour",
    "hours", "before", "after", "again", "look", "looks", "good", "chance",
    "have", "had", "she", "her", "his", "ask", "asking", "corrected", "current",
    "send", "forward", "just", "your", "ours", "them", "they", "into", "onto",
    "text", "ping", "shoot", "block", "push", "running", "late", "where",
})
# Desktop and web apps a command may open by name.
APPS = frozenset({
    "slack", "gmail", "mail", "calendar", "google calendar", "figma", "notes", "notion", "linear", "jira",
    "github", "zoom", "chrome", "safari", "firefox", "terminal", "finder", "spotify", "messages",
    "excel", "word", "powerpoint", "keynote", "numbers", "pages", "google docs", "google sheets", "docs",
    "sheets", "drive", "google drive", "dropbox", "salesforce", "hubspot", "loom", "miro", "asana",
    "trello", "vs code", "vscode", "cursor", "xcode", "teams", "outlook", "chatgpt", "codex", "settings",
})
_HOUR_WORD = {"an": 1, "a": 1, "one": 1, "two": 2, "three": 3, "four": 4}
_WHEN = re.compile(
    r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2})\s+to\s+"
    r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2})"
)


def plan(corpus: Corpus, command: str, as_of: datetime, trace: dict | None = None) -> list[dict]:
    """Return dry-run actions for one command. The list may be a single clarify or confirm.

    `trace`, when given, gets "reader": which path split the command (model, cache, rules, fallback).
    """
    trace = {} if trace is None else trace
    trace["reader"] = "rules"
    command = " ".join(command.split())
    world = _world(corpus)
    if _INJECTION.search(command) or _mentions_blocked(command, world["blocked"]):
        return _finish([_clarify("That text is an instruction found in a message. I won't act on it.")])
    if _DESTRUCTIVE.search(command):
        return _finish([{"type": "confirm", "args": {"summary": command}}])
    if _is_question(command):
        return _finish([{"type": "memory.ask", "args": {"question": command}}])

    shown = visible(corpus, as_of)
    clauses, trace["reader"] = rewrite(command)
    actions: list[dict] = []
    for clause in clauses or _clauses(command):
        actions.extend(_one(world, shown, clause, as_of))
    return _finish(_drop_blocked(actions, world["blocked"]))


def _one(world: dict, shown: list[Record], clause: str, as_of: datetime) -> list[dict]:
    if re.match(r"^open\b", clause, re.IGNORECASE):
        return [_open(shown, clause)]
    if re.match(r"^(move|reschedule|shift|push)\b", clause, re.IGNORECASE):
        return [_move(shown, clause, as_of)]
    if re.match(r"^(book|schedule|block)\b", clause, re.IGNORECASE):
        return [_book(world, shown, clause, as_of)]
    if _memory_question(clause, as_of):
        return [{"type": "memory.ask", "args": {"question": clause}}]
    if re.match(r"^remind\b", clause, re.IGNORECASE) or re.search(
        r"\bset a reminder\b", clause, re.IGNORECASE
    ):
        return [_remind(shown, clause, as_of)]
    return [_deliver(world, shown, clause, as_of)]


def _open(shown: list[Record], clause: str) -> dict:
    """An app opens. Anything else is something in memory, or a question back."""
    target = re.sub(r"^open\s+(?:up\s+)?", "", clause, flags=re.IGNORECASE).strip(" .")
    if re.sub(r"\s+app$", "", target.lower()) in APPS:
        return {"type": "app.open", "args": {"app": target}}
    terms = [word for word in re.findall(r"[a-z0-9]+", target.lower()) if len(word) >= 3 and word not in _GLUE and word not in _NOT_A_NAME]
    if terms and any(all(term in record.text.lower() for term in terms[:3]) for record in shown if not is_untrusted(record)):
        return {"type": "memory.ask", "args": {"question": f"Find {target}"}}
    return _clarify(f"I don't know an app or a record called {target}. What should I open?")


def _move(shown: list[Record], clause: str, as_of: datetime) -> dict:
    clock = _clock(clause)
    event = _best_event(shown, _event_phrase(clause), as_of)
    if clock is None or event is None:
        return _clarify("Which event should move, and to what time?")
    start = event.event_time.astimezone(LA)
    end = _event_end(event) or (start + timedelta(hours=1))
    new_start = start.replace(hour=clock[0], minute=clock[1], second=0, microsecond=0)
    new_end = new_start + (end - start)
    return {
        "type": "calendar.update_event",
        "args": {"event_id": event.id, "start": _iso(new_start), "end": _iso(new_end)},
    }


def _book(world: dict, shown: list[Record], clause: str, as_of: datetime) -> dict:
    people, question = _with_outsiders(world["directory"], clause, shown)
    if question:
        return _clarify(question)
    if not people:
        return _clarify("Who should I book time with?")
    addresses = []
    for person in people:
        address = _address(person, world["emails"])
        if not address:
            return _clarify(f"I don't have an email for {person.full}.")
        addresses.append(address)
    day = _day(clause, as_of) or as_of.astimezone(LA).date()
    hour, minute = _clock(clause) or (9, 0)
    start = datetime(day.year, day.month, day.day, hour, minute, tzinfo=LA)
    title = _purpose(clause) or " / ".join(person.full for person in people)
    return {
        "type": "calendar.create_event",
        "args": {
            "title": title,
            "start": _iso(start),
            "end": _iso(start + _duration(clause)),
            "attendees": addresses,
        },
    }


def _remind(shown: list[Record], clause: str, as_of: datetime) -> dict:
    before = re.search(
        r"\b(an|a|one|two|three|\d+)\s+hours?\s+before\s+(?:the\s+)?(.+?)\s+to\s+(.+)$",
        clause,
        re.IGNORECASE,
    )
    if before:
        event = _best_event(shown, before.group(2), as_of)
        if event is None:
            return _clarify("Which event is that reminder before?")
        hours = _hour_count(before.group(1))
        due = event.event_time.astimezone(LA) - timedelta(hours=hours)
        return {"type": "reminder.create", "args": {"text": before.group(3).strip(), "due": _iso(due)}}

    day = _day(clause, as_of)
    if day is None:
        return _clarify("When should I remind you?")
    hour, minute = _clock(clause) or (9, 0)
    due = datetime(day.year, day.month, day.day, hour, minute, tzinfo=LA)
    return {"type": "reminder.create", "args": {"text": _reminder_text(clause), "due": _iso(due)}}


def _deliver(world: dict, shown: list[Record], clause: str, as_of: datetime) -> dict:
    channel, question = _channel(clause, world)
    if question:
        return _clarify(question)
    body = _utterance(clause)
    named = _REFERENCE.match(clause) if body == clause else None
    if named and not names_a_thing(named.group(1)):
        named = None
    if named:
        found = _recall(world, f"What is {named.group(1).strip(' .')}?", as_of)
        if found is None:
            return _clarify(f"I couldn't find {named.group(1).strip(' .')} in what I have. What should it say?")
        body = found
    if channel:
        return {"type": "slack.send_message", "args": {"to": channel, "text": body}}

    rest, cc_text = _split_cc(clause)
    cc_people: list[Person] = []
    if cc_text:
        cc_people, question = _with_outsiders(world["directory"], f"cc {cc_text}", shown)
        if question:
            return _clarify(question)
    people, question = _with_outsiders(world["directory"], rest, shown)
    if question:
        return _clarify(question)
    if not people:
        return _clarify("Who should I contact?")
    if cc_people or (_wants_email(clause) and len(people) > 1):
        return _mail(world, people, cc_people, clause, body)
    person = people[0]
    if _wants_email(clause) or not person.slack_id:
        return _mail(world, [person], [], clause, body)
    return {"type": "slack.send_message", "args": {"to": person.slack_id, "text": body}}


# "Email John the corrected NRR": the message is a thing named, to be looked up, not words to send.
_REFERENCE = re.compile(
    r"^(?:email|send|forward|message|tell|text|slack|ping|give)\s+\S+(?:\s+[A-Z][a-z]+)?\s+"
    r"((?:the|our|my|their|his|her|latest|current)\s+.+?)(?:\s+(?:on slack|by email|over email))?$",
    re.IGNORECASE,
)


def _recall(world: dict, question: str, as_of: datetime) -> str | None:
    """Memory's answer as of the command's time, or None when memory does not know."""
    from candor.retrieve import retrieve
    from candor.writer import respond

    corpus = world["corpus"]
    ranked = retrieve(corpus, question, as_of, stem=True)
    answer, _sources, abstained, _origin = respond(corpus, question, as_of, ranked)
    return None if abstained else answer


def _mail(world: dict, people: list[Person], copied: list[Person], clause: str, body: str) -> dict:
    to = []
    for person in people:
        address = _address(person, world["emails"])
        if not address:
            return _clarify(f"I don't have an email for {person.full}.")
        to.append(address)
    args: dict = {"to": to, "subject": _subject(clause), "body": body}
    cc = []
    for person in copied:
        address = _address(person, world["emails"])
        if not address:
            return _clarify(f"I don't have an email for {person.full}.")
        cc.append(address)
    if cc:
        args["cc"] = cc
    return {"type": "gmail.send", "args": args}


def _memory_question(clause: str, as_of: datetime) -> bool:
    """'Remind me what we decided' asks memory. A reminder has a time."""
    if not re.match(
        r"^remind me\s+(what|when|who|why|how|where|whether)\b",
        clause,
        re.IGNORECASE,
    ):
        return False
    if re.search(r"\bbefore\b", clause, re.IGNORECASE):
        return False
    return _day(clause, as_of) is None and _clock(clause) is None


def _parties(
    directory: Directory, clause: str, shown: list[Record]
) -> tuple[list[Person], str | None]:
    """Every person the clause names. A shared first name needs a topic or a full name."""
    named = _named(directory, clause)
    if len(named) <= 1:
        return named, None
    lowered = clause.lower()
    by_first: dict[str, list[Person]] = {}
    for person in named:
        by_first.setdefault(person.first, []).append(person)
    chosen: list[Person] = []
    ambiguous: list[Person] = []
    for group in by_first.values():
        full = [person for person in group if person.full.lower() in lowered]
        if full:
            chosen.extend(full)
        elif len(group) == 1:
            chosen.append(group[0])
        else:
            picked = _pick(group, clause, shown)
            if picked is None:
                ambiguous.extend(group)
            else:
                chosen.append(picked)
    if ambiguous:
        names = " or ".join(person.full for person in sorted(ambiguous, key=lambda person: person.full))
        return [], f"Which person: {names}?"
    return chosen, None


# A name in a recipient slot: right after the verb, or after with / cc / to / and / a comma.
_CAPITALIZED = re.compile(r"(?:^[A-Za-z]+|\bwith|\bcc|\bto|\band|,)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b")
_NOT_PEOPLE = frozenset({
    "slack", "email", "gmail", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
    "november", "december", "i", "ok", "okay", "thanks", "hi", "hello", "please",
})


def _with_outsiders(directory: Directory, clause: str, shown: list[Record]) -> tuple[list[Person], str | None]:
    """Everyone the clause names: directory people, then names found only in memory."""
    people, question = _parties(directory, clause, shown)
    if question:
        return [], question
    known = {part for person in directory.people for part in (person.first, person.last)}
    for match in _CAPITALIZED.finditer(clause):
        name = match.group(1)
        parts = name.lower().split()
        if parts[0] in _NOT_PEOPLE or (len(parts) == 1 and parts[0] in known):
            continue
        if any(person.full.lower() == name.lower() for person in directory.people):
            continue
        if len(parts) == 2 and parts[0] in known and parts[1] in _NOT_PEOPLE:
            continue
        address, problem = _lookup_address(name, shown)
        if problem:
            return [], problem
        people.append(Person(key=name.lower(), full=name, first=parts[0], last=parts[-1],
                             emails=frozenset({address}), slack_id=None))
    return people, None


def _lookup_address(name: str, shown: list[Record]) -> tuple[str | None, str | None]:
    """One address written next to the name in a trusted record, or the question to ask instead."""
    pattern = re.compile(rf"\b{re.escape(name)}\b", re.IGNORECASE)
    first = name.split()[0].lower()
    seen_name = False
    found: set[str] = set()
    for record in shown:
        if is_untrusted(record):
            continue
        for hit in pattern.finditer(record.text):
            seen_name = True
            nearby = record.text[max(0, hit.start() - 80): hit.end() + 80].lower()
            found |= {email for email in _EMAIL.findall(nearby) if email.split("@")[0].startswith(first)}
    if len(found) == 1:
        return found.pop(), None
    if len(found) > 1:
        return None, f"I found more than one address for {name}: {', '.join(sorted(found))}. Which one?"
    if seen_name:
        return None, f"I don't have an email for {name}."
    return None, f"I don't know who {name} is."


def _split_cc(clause: str) -> tuple[str, str]:
    match = re.search(r"\bcc\s+(.+?)(?=\s*,\s*that\b|\s+that\b|$)", clause, re.IGNORECASE)
    if not match:
        return clause, ""
    copied = match.group(1).strip(" ,")
    rest = f"{clause[:match.start()]} {clause[match.end():]}"
    return " ".join(rest.split()), copied


def _named(directory: Directory, text: str) -> list[Person]:
    lowered = text.lower()
    full = [person for person in directory.people if person.full.lower() in lowered]
    # A full name uses up its first name; other first names in the clause still count.
    for person in full:
        lowered = lowered.replace(person.full.lower(), " ")
    found: list[Person] = list(full)
    seen: set[str] = {person.key for person in full}
    for person in directory.people:
        if person.key in seen:
            continue
        if person.first in _NOT_A_NAME:
            continue
        if re.search(rf"\b{re.escape(person.first)}\b", lowered):
            found.append(person)
            seen.add(person.key)
    return found


def _pick(candidates: list[Person], clause: str, shown: list[Record]) -> Person | None:
    """The person who uniquely owns the rarest topic word. A tie asks instead."""
    names = {person.first for person in candidates} | {person.last for person in candidates}
    tokens = [
        token for token in re.findall(r"[a-z0-9]+", clause.lower())
        if len(token) >= 4 and token not in _GLUE and token not in names
    ]
    if not tokens:
        return None

    def owns(person: Person, token: str) -> bool:
        return any(_about(person, record) and token in record.text.lower() for record in shown)

    weights = []
    for token in set(tokens):
        df = sum(token in record.text.lower() for record in shown)
        weights.append((token, 1 / (df or 1)))
    scored = []
    for person in candidates:
        score = sum(weight for token, weight in weights if owns(person, token))
        scored.append((score, person.full, person))
    scored.sort(key=lambda item: (-item[0], item[1]))
    if scored[0][0] <= 0:
        return None
    if len(scored) == 1 or scored[0][0] > scored[1][0]:
        return scored[0][2]
    return None


def _about(person: Person, record: Record) -> bool:
    if person.slack_id and record.author_id == person.slack_id:
        return True
    lowered = record.text.lower()
    if any(email in lowered for email in person.emails):
        return True
    if person.full.lower() in lowered:
        return True
    return False


def _utterance(clause: str) -> str:
    if re.match(r"^thank\b", clause, re.IGNORECASE):
        return "Thanks"
    match = re.search(r"^[^:]{1,60}:\s*(.+)", clause) or re.search(r"^let\s+.+?\s+know\s+(?:that\s+)?(.+)", clause, re.IGNORECASE)
    if match:
        return match.group(1).rstrip(".")
    match = re.search(r"\b(?:that|we're|we are)\s+(.+)", clause, re.IGNORECASE)
    if match:
        return match.group(1).rstrip(".")
    match = re.search(r"\babout\s+(.+)", clause, re.IGNORECASE)
    if match:
        return match.group(1).rstrip(".")
    match = re.search(r"\bask\s+(.+)", clause, re.IGNORECASE)
    if match:
        return match.group(1).rstrip(".")
    return clause


def _reminder_text(clause: str) -> str:
    """The task, whether it sits before the clock or after it."""
    prefixed = re.sub(r"^remind me to\s+", "", clause, flags=re.IGNORECASE)
    if prefixed != clause:
        task = re.split(
            r"\b(?:on the \d+(?:st|nd|rd|th)?|tomorrow|at \d+)\b",
            prefixed,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0]
        return task.strip(" ,.") or clause
    match = re.search(r"\bto\s+(.+)$", clause, re.IGNORECASE)
    return match.group(1).strip(" ,.") if match else clause


def _best_event(shown: list[Record], phrase: str, as_of: datetime) -> Record | None:
    tokens = [
        token for token in re.findall(r"[a-z0-9]+", phrase.lower())
        if len(token) > 2 and token not in _GLUE
    ]
    one_on_one = re.search(r"\b1[:\- ]1\b|one[- ]on[- ]one", phrase, re.IGNORECASE)
    best: Record | None = None
    best_score = 0
    for record in shown:
        if record.source != "calendar":
            continue
        summary, _, rest = record.text.lower().partition("|")
        if one_on_one and not re.search(r"1[:\- ]1|one[- ]on[- ]one", summary):
            continue
        attendees = rest.split("attendees:", 1)[-1] if "attendees:" in rest else ""
        score = sum(token in summary for token in tokens) * 2
        score += sum(token in attendees for token in tokens)
        if score < best_score or score == 0:
            continue
        if score > best_score or _closer(record, best, as_of):
            best = record
            best_score = score
    return best


def _closer(candidate: Record, current: Record | None, as_of: datetime) -> bool:
    if current is None:
        return True
    return abs(candidate.event_time - as_of) < abs(current.event_time - as_of)


def _event_phrase(clause: str) -> str:
    text = re.sub(r"^(move|reschedule|shift|push)\s+", "", clause, flags=re.IGNORECASE)
    text = re.sub(r"\bto\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?\b", "", text, flags=re.IGNORECASE)
    return text.strip()


def _event_end(record: Record) -> datetime | None:
    match = _WHEN.search(record.text)
    if not match:
        return None
    return datetime.fromisoformat(match.group(2))


_RECIPIENT = re.compile(
    r"^(?:tell|message|ping|slack|text|post (?:in|to)|update|let|notify|announce to|send)\s+(.+?)"
    r"(?=\s+(?:that|know|about|we'?re|we are|on slack)\b|:|,|$)",
    re.IGNORECASE,
)
_GROUP_FILLER = frozenset({"the", "our", "my", "in", "to", "on", "folks", "team", "people", "crew", "group", "everyone", "all", "whole", "gang"})
_EVERYONE = re.compile(r"\b(everyone|everybody|the whole company|whole team|all hands|the company)\b", re.IGNORECASE)


def _channel(clause: str, world: dict) -> tuple[str | None, str | None]:
    """A channel the clause names, by name, by '#', or by a word from its topic. (id, question)."""
    channels, topics = world["channels"], world.get("topics", {})
    if re.search(r"\bchannel\b|#", clause, re.IGNORECASE):
        folded = re.sub(r"[^a-z0-9]", "", clause.lower())
        matches = [(cid, name) for cid, name in channels.items() if re.sub(r"[^a-z0-9]", "", name) in folded]
        if matches:
            return max(matches, key=lambda item: len(item[1]))[0], None
    found = _RECIPIENT.match(clause)
    if not found:
        return None, None
    phrase = found.group(1)
    if found.end() == len(clause):
        # No word marks where the recipient ends, so only the first few words can name it.
        phrase = " ".join(phrase.split()[:3])
    if _named(world["directory"], phrase):
        return None, None
    words = [word for word in re.findall(r"[a-z0-9]+", phrase.lower()) if word not in _GROUP_FILLER]
    if _EVERYONE.search(phrase):
        words.append("company")
    if not words:
        return None, None
    by_name = [cid for cid, name in channels.items() if set(re.findall(r"[a-z0-9]+", name.lower())) <= set(words)]
    if not by_name:
        by_name = [cid for cid, name in channels.items() if re.findall(r"[a-z0-9]+", name.lower())[0] in words]
    candidates = by_name or [
        cid for cid, topic in topics.items()
        if set(words) & {word for word in re.findall(r"[a-z0-9]+", topic.lower()) if len(word) >= 2 and word not in _NOT_A_NAME}
    ]
    if len(candidates) == 1:
        return candidates[0], None
    if len(candidates) > 1:
        names = " or ".join(f"#{channels[cid]}" for cid in sorted(candidates, key=channels.get))
        return None, f"Which channel: {names}?"
    return None, None


def _clauses(command: str) -> list[str]:
    parts = re.split(r"\s+and\s+", command, flags=re.IGNORECASE)
    merged = [parts[0].strip()]
    for part in parts[1:]:
        part = part.strip()
        if _SPLIT_VERB.match(part):
            merged.append(part)
        else:
            merged[-1] = f"{merged[-1]} and {part}"
    return merged


def _is_question(command: str) -> bool:
    if _IMPERATIVE.search(command):
        return False
    return command.endswith("?") or _QUESTION.match(command) is not None


def _wants_email(clause: str) -> bool:
    if re.match(r"^(email|forward|send)\b", clause, re.IGNORECASE):
        return True
    return re.search(r"\b(?:an|a)\s+e-?mails?\b", clause, re.IGNORECASE) is not None


def _clock(text: str) -> tuple[int, int] | None:
    match = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", text, re.IGNORECASE)
    if match:
        return _apply_ampm(int(match.group(1)), int(match.group(2) or 0), match.group(3))
    match = re.search(r"\bat\s+(\d{1,2})(?::(\d{2}))?\b", text, re.IGNORECASE)
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    if 1 <= hour <= 7:
        hour += 12
    return hour, minute


def _apply_ampm(hour: int, minute: int, ampm: str) -> tuple[int, int]:
    ampm = ampm.lower()
    if ampm == "pm" and hour < 12:
        hour += 12
    if ampm == "am" and hour == 12:
        hour = 0
    return hour, minute


def _day(text: str, as_of: datetime) -> datetime.date | None:
    local = as_of.astimezone(LA)
    if re.search(r"\bday after tomorrow\b", text, re.IGNORECASE):
        return (local + timedelta(days=2)).date()
    if re.search(r"\btomorrow\b", text, re.IGNORECASE):
        return (local + timedelta(days=1)).date()
    later = re.search(r"\bin\s+(\d+|two|three)\s+days?\b", text, re.IGNORECASE)
    if later:
        count = later.group(1).lower()
        days = int(count) if count.isdigit() else {"two": 2, "three": 3}[count]
        return (local + timedelta(days=days)).date()
    weekday = re.search(
        r"\b(next\s+)?(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
        text,
        re.IGNORECASE,
    )
    if weekday:
        names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        target = names.index(weekday.group(2).lower())
        start = 1 if weekday.group(1) else 0
        for offset in range(start, start + 7):
            candidate = local + timedelta(days=offset)
            if candidate.weekday() == target:
                return candidate.date()
    match = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)\b", text, re.IGNORECASE)
    if not match:
        return None
    day = int(match.group(1))
    year, month = local.year, local.month
    if day < local.day:
        month += 1
        if month > 12:
            month = 1
            year += 1
    return datetime(year, month, day).date()


def _duration(text: str) -> timedelta:
    match = re.search(r"\b(\d+)\s+minutes?\b", text, re.IGNORECASE)
    if match:
        return timedelta(minutes=int(match.group(1)))
    match = re.search(r"\b(an|a|one|two|three|\d+)\s+hours?\b", text, re.IGNORECASE)
    if match:
        return timedelta(hours=_hour_count(match.group(1)))
    return timedelta(minutes=30)


def _hour_count(word: str) -> int:
    word = word.lower()
    if word.isdigit():
        return int(word)
    return _HOUR_WORD.get(word, 1)


def _purpose(clause: str) -> str | None:
    about = _about_phrase(clause)
    if about:
        return about
    match = re.search(
        r"\bto\s+((?:go over|talk about|discuss|review|walk through)\s+.+)$",
        clause,
        re.IGNORECASE,
    )
    if not match:
        return None
    return match.group(1).strip(" .")


def _about_phrase(clause: str) -> str | None:
    match = re.search(r"\babout\s+(?:the\s+)?(.+)", clause, re.IGNORECASE)
    if not match:
        return None
    return match.group(1).strip(" .")


def _subject(clause: str) -> str:
    phrase = _about_phrase(clause)
    if phrase:
        return phrase[:80]
    terms = re.findall(r"\b[A-Z]{2,5}\b", clause)
    return terms[0] if terms else "Note"


def _address(person: Person, by_slack: dict[str, str]) -> str | None:
    if person.slack_id and by_slack.get(person.slack_id):
        return by_slack[person.slack_id]
    if person.emails:
        return sorted(person.emails)[0]
    return None


def _clarify(question: str) -> dict:
    return {"type": "clarify", "args": {"question": question}}


def _mentions_blocked(command: str, blocked: set[str]) -> bool:
    lowered = command.lower()
    return any(address in lowered for address in blocked)


def _drop_blocked(actions: list[dict], blocked: set[str]) -> list[dict]:
    kept = []
    for action in actions:
        if action["type"] != "gmail.send":
            kept.append(action)
            continue
        recipients = [item.lower() for item in action["args"].get("to", [])]
        if blocked.intersection(recipients):
            kept.append(_clarify("I won't send to an address that only appears in an untrusted message."))
        else:
            kept.append(action)
    return kept


def _finish(actions: list[dict]) -> list[dict]:
    cleaned = []
    for action in actions:
        args = {key: _clean_value(value) for key, value in action["args"].items()}
        cleaned.append({"type": action["type"], "args": args})
    return cleaned


def _clean_value(value):
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, list):
        return [_clean_value(item) for item in value]
    return value


def _iso(moment: datetime) -> str:
    return moment.astimezone(LA).isoformat(timespec="seconds")


def _world(corpus: Corpus) -> dict:
    cached = getattr(corpus, "_action_world", None)
    if cached is not None:
        return cached
    root = corpus.data_dir or default_data_dir()
    users = json.loads((root / "connectors" / "slack" / "users.json").read_text(encoding="utf-8"))
    emails = {user["id"]: user["email"] for user in users if user.get("email")}
    channels: dict[str, str] = {}
    topics: dict[str, str] = {}
    listing = root / "connectors" / "slack" / "channels.json"
    if listing.exists():
        for channel in json.loads(listing.read_text(encoding="utf-8")):
            if channel.get("is_dm"):
                continue
            channels[channel["id"]] = channel["name"]
            topics[channel["id"]] = channel.get("topic") or ""
    blocked: set[str] = set()
    trusted: set[str] = set()
    for record in corpus.records:
        found = set(_EMAIL.findall(record.text.lower()))
        if is_untrusted(record):
            blocked |= found
        else:
            trusted |= found
        if record.source == "slack" and record.channel and not record.channel.startswith("D-"):
            match = re.match(r"\[Slack ([^,\]]+)", record.text)
            if match and record.channel not in channels:
                channels[record.channel] = match.group(1).strip()
    world = {
        "directory": build_directory(corpus),
        "emails": emails,
        "channels": channels,
        "topics": topics,
        "blocked": blocked - trusted,
        "corpus": corpus,
    }
    corpus._action_world = world
    return world
