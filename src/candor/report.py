"""Per-question retrieval failures: missed groups, forbidden ids, first hit."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from candor.models import Corpus


def _load_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _needed(item: dict) -> list[list[str]]:
    return item.get("needed") or [[entry] for entry in item.get("evidence", [])]


def write_failure_report(corpus: Corpus, gold_path: Path, answers_path: Path, out_path: Path) -> str:
    """Write a line per gold question. Return the same text."""
    record_of = {record.id: record.parent_id for record in corpus.records}
    avail = {record.id: record.available_at for record in corpus.records}
    for record in corpus.records:
        current = avail.get(record.parent_id)
        if current is None or record.available_at < current:
            avail[record.parent_id] = record.available_at
    answers = {row["id"]: row for row in _load_jsonl(answers_path)}
    lines = []
    for item in _load_jsonl(gold_path):
        answer = answers.get(item["id"], {})
        retrieved = [str(value) for value in answer.get("retrieved") or []]
        top10 = retrieved[:10]
        top20 = retrieved[:20]
        as_of = datetime.fromisoformat(item["as_of"])
        harm = []
        for rank, cid in enumerate(top20, start=1):
            when = avail.get(cid)
            if when is not None and when > as_of:
                harm.append(f"{cid} not yet delivered @{rank}")
            elif cid in corpus.deleted and corpus.deleted[cid] <= as_of:
                harm.append(f"{cid} deleted @{rank}")
        groups = _needed(item) if item.get("answerable") else []
        missed = []
        first = None
        if groups:
            top_set = set(top10)
            top_recs = {record_of.get(cid, cid) for cid in top10}
            for group in groups:
                hit = any(member in top_set or (member not in record_of and member in top_recs) for member in group)
                if not hit:
                    missed.append(",".join(group))
            for index, cid in enumerate(top20, start=1):
                parent = record_of.get(cid, cid)
                if any(cid in group or (parent in group and parent not in record_of) for group in groups):
                    first = index
                    break
            harm10 = [entry for entry in harm if int(entry.rsplit("@", 1)[-1]) <= 10]
            status = "PASS" if not missed and not harm10 else "FAIL"
            detail = f"missed=[{' | '.join(missed)}] first@{first}"
        else:
            harm20 = harm
            status = "PASS" if not harm20 else "FAIL"
            detail = "abstention, harm check on top 20"
        harm_text = f" forbidden=[{'; '.join(harm)}]" if harm else ""
        lines.append(f"{item['id']} {status} {item.get('category', '')} {detail}{harm_text}")
    text = "\n".join(lines) + "\n"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8")
    return text
