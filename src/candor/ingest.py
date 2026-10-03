"""Load every source in `data/` into one record list.

Delivery times match `eval_harness/records.py`: a meeting segment exists at
meeting start + `end_s`, a calendar event at `updated`, a Codex session at its
last event, and everything else at its own timestamp. Codex sessions are one
id. Meeting segments and ChatGPT messages keep their real sub-ids.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from candor.models import Corpus, Record

LA = ZoneInfo("America/Los_Angeles")
ALEX_ID = "U01ALEX"
ALEX_NAME = "Alex Rivera"


def default_data_dir() -> Path:
    """Repo `data/` directory, or `CANDOR_DATA` when the package is not checked out."""
    override = os.environ.get("CANDOR_DATA")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[2] / "data"


def load_corpus(data_dir: str | Path | None = None) -> Corpus:
    """Read the package and return units in delivery order."""
    root = Path(data_dir) if data_dir is not None else default_data_dir()
    records: list[Record] = []
    records.extend(_meetings(root))
    records.extend(_dictations(root))
    slack_records, deleted, edits = _slack(root)
    records.extend(slack_records)
    records.extend(_gmail(root))
    records.extend(_calendar(root))
    records.extend(_codex(root))
    records.extend(_chatgpt(root))
    records.sort(key=lambda record: record.available_at)
    return Corpus(records=records, deleted=deleted, edits=edits, data_dir=root)


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _jsonl(path: Path):
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def _meetings(root: Path) -> list[Record]:
    records = []
    for path in sorted((root / "native" / "meetings").glob("*.json")):
        meeting = _read_json(path)
        start = _dt(meeting["start"])
        participants = tuple(meeting.get("participants_known") or [])
        for segment in meeting["segments"]:
            name = segment.get("speaker_name")
            who = name or segment.get("speaker_label") or "Unknown speaker"
            available = start + timedelta(seconds=segment["end_s"])
            records.append(Record(
                id=segment["seg_id"],
                parent_id=meeting["id"],
                source="meeting",
                kind="segment",
                author=who,
                author_id=None,
                participants=participants,
                event_time=available,
                available_at=available,
                text=f"[{meeting['title']}, {meeting['start'][:10]}] {who}: {segment['text']}",
                body=segment["text"],
                thread_id=meeting["id"],
                channel=segment.get("channel"),
                speaker_confidence=segment.get("speaker_confidence"),
                speaker_identified=bool(name),
            ))
    return records


def _dictations(root: Path) -> list[Record]:
    records = []
    for item in _jsonl(root / "native" / "dictation" / "dictations.jsonl"):
        raw = item.get("raw_transcript")
        suffix = f"\n(raw transcript: {raw})" if raw else ""
        cleaned = item["cleaned_text"]
        records.append(Record(
            id=item["id"],
            parent_id=item["id"],
            source="dictation",
            kind="dictation",
            author=ALEX_NAME,
            author_id=ALEX_ID,
            participants=(),
            event_time=_dt(item["timestamp"]),
            available_at=_dt(item["timestamp"]),
            text=(
                f"[Dictation {item['mode']} into {item['target_app']} \u2013 {item['target_context']}, "
                f"{item['delivery_state']}] {cleaned}{suffix}"
            ),
            body=cleaned,
            channel=item.get("target_app"),
        ))
    return records


def _slack(root: Path) -> tuple[list[Record], dict[str, datetime], dict[str, list[tuple[datetime, str]]]]:
    names = {user["id"]: user["real_name"] for user in _read_json(root / "connectors" / "slack" / "users.json")}
    channels = {channel["id"]: channel["name"] for channel in _read_json(root / "connectors" / "slack" / "channels.json")}
    records: list[Record] = []
    deleted: dict[str, datetime] = {}
    edits: dict[str, list[tuple[datetime, str]]] = {}
    for item in _jsonl(root / "connectors" / "slack" / "messages.jsonl"):
        when = _dt(item["ts"])
        where = channels.get(item["channel_id"], item["channel_id"])
        subtype = item.get("subtype")
        if subtype == "message_deleted":
            deleted[item["target_id"]] = when
            records.append(Record(
                id=item["id"],
                parent_id=item["id"],
                source="slack",
                kind="deletion",
                author=None,
                author_id=None,
                participants=(),
                event_time=when,
                available_at=when,
                text=f"[Slack {where}] (message {item['target_id']} was deleted)",
                body="",
                thread_id=item.get("thread_parent_id"),
                target_id=item["target_id"],
                channel=item["channel_id"],
            ))
            continue
        if subtype == "message_changed":
            edits.setdefault(item["target_id"], []).append((when, item["text"]))
            records.append(Record(
                id=item["id"],
                parent_id=item["id"],
                source="slack",
                kind="edit",
                author=None,
                author_id=None,
                participants=(),
                event_time=when,
                available_at=when,
                text=f"[Slack {where}, edit of {item['target_id']}] {item['text']}",
                body=item["text"],
                thread_id=item.get("thread_parent_id"),
                target_id=item["target_id"],
                channel=item["channel_id"],
            ))
            continue
        author_id = item.get("user")
        author = names.get(author_id, item.get("bot_name") or author_id)
        records.append(Record(
            id=item["id"],
            parent_id=item["id"],
            source="slack",
            kind="message",
            author=author,
            author_id=author_id,
            participants=(author_id,) if author_id else (),
            event_time=when,
            available_at=when,
            text=f"[Slack {where}] {author}: {item['text']}",
            body=item.get("text") or "",
            thread_id=item.get("thread_parent_id"),
            channel=item["channel_id"],
        ))
    return records, deleted, edits


def _gmail(root: Path) -> list[Record]:
    records = []
    for item in _jsonl(root / "connectors" / "gmail" / "messages.jsonl"):
        when = _dt(item["date"])
        cc = f" Cc {', '.join(item['cc'])}" if item["cc"] else ""
        people = (item["from"], *(item.get("to") or []), *(item.get("cc") or []))
        records.append(Record(
            id=item["id"],
            parent_id=item["id"],
            source="gmail",
            kind="email",
            author=item["from"],
            author_id=None,
            participants=tuple(people),
            event_time=when,
            available_at=when,
            text=(
                f"[Email {item['date'][:16]}] From {item['from']} To {', '.join(item['to'])}"
                f"{cc} | {item['subject']}\n{item['body']}"
            ),
            body=item["body"],
            thread_id=item.get("thread_id"),
        ))
    return records


def _calendar_start(value: dict) -> datetime:
    if value.get("dateTime"):
        return _dt(value["dateTime"])
    return datetime.fromisoformat(value["date"]).replace(tzinfo=LA)


def _calendar(root: Path) -> list[Record]:
    records = []
    for item in _jsonl(root / "connectors" / "google_calendar" / "events.jsonl"):
        start, end = item["start"], item["end"]
        when = f"{start.get('dateTime') or start.get('date')} to {end.get('dateTime') or end.get('date')}"
        attendees = tuple(person["email"] for person in item.get("attendees") or [])
        updated = _dt(item["updated"])
        repeat = f" | repeats {item['recurrence']}" if item.get("recurrence") else ""
        records.append(Record(
            id=item["id"],
            parent_id=item["id"],
            source="calendar",
            kind="event",
            author=item.get("organizer"),
            author_id=None,
            participants=attendees,
            event_time=_calendar_start(start),
            available_at=updated,
            text=(
                f"[Calendar, {item['status']}] {item['summary']} | {when} | {item.get('location') or ''} | "
                f"attendees: {', '.join(attendees)} | {item.get('description') or ''}{repeat}"
            ),
            body=item.get("description") or "",
        ))
    return records


def _codex(root: Path) -> list[Record]:
    records = []
    session_dir = root / "connectors" / "codex" / "sessions"
    for path in sorted(session_dir.glob("*.jsonl")):
        events = list(_jsonl(path))
        meta, body = events[0], events[1:]
        lines = []
        for event in body:
            role = event.get("role", event.get("tool", event["type"]))
            content = event.get("content") or event.get("input", "")
            lines.append(f"{role}: {content}")
        when = _dt(body[-1]["timestamp"] if body else meta["started_at"])
        records.append(Record(
            id=meta["id"],
            parent_id=meta["id"],
            source="codex",
            kind="session",
            author=ALEX_NAME,
            author_id=ALEX_ID,
            participants=(),
            event_time=when,
            available_at=when,
            text=f"[Codex session, repo {meta.get('repo')}]\n" + "\n".join(lines),
            body="\n".join(lines),
        ))
    return records


def _chatgpt(root: Path) -> list[Record]:
    records = []
    for conversation in _read_json(root / "connectors" / "chatgpt" / "conversations.json"):
        for message in conversation["messages"]:
            when = _dt(message["create_time"])
            is_user = message["role"] == "user"
            records.append(Record(
                id=message["id"],
                parent_id=conversation["id"],
                source="chatgpt",
                kind="message",
                author=ALEX_NAME if is_user else "ChatGPT",
                author_id=ALEX_ID if is_user else None,
                participants=(),
                event_time=when,
                available_at=when,
                text=f"[ChatGPT '{conversation['title']}'] {message['role']}: {message['content']}",
                body=message["content"],
                thread_id=conversation["id"],
            ))
    return records
