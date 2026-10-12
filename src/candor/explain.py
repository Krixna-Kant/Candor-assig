"""A short account of one answer: what was visible, what was retrieved, what was quoted."""

from __future__ import annotations

from datetime import datetime

from candor.models import Corpus, Record
from candor.redact import redact
from candor.retrieve import retrieve
from candor.textnorm import analyze
from candor.timeline import visible
from candor.writer import evidence, respond


def explain_text(corpus: Corpus, question: str, as_of: datetime) -> str:
    """Plain text a person can read. Does not change retrieval or the answer."""
    pool = visible(corpus, as_of)
    ranked = retrieve(corpus, question, as_of, stem=True)
    answer, sources, abstained, origin = respond(corpus, question, as_of, ranked)
    answer = redact(answer)
    query = set(analyze(question, stem=True, expand=True))
    shown = [record.id for record in evidence(ranked)]
    lines = [
        f"Question: {question}",
        f"As of: {as_of.isoformat()}",
        f"Visible: {len(pool)} of {len(corpus.records)} records",
        "",
        "Answer",
        answer,
        f"Abstained: {'yes' if abstained else 'no'}",
        f"Sources: {', '.join(sources) if sources else '(none)'}",
        f"Writer: {origin.split(':', 1)[0]}",
        f"Records a model may read: {', '.join(shown) if shown else '(none)'}",
        "",
        "Retrieved, best first",
    ]
    for index, record in enumerate(ranked[:8], start=1):
        lines.append(f"{index}. {record.id}  {record.source}")
        lines.append(f"   {_why(record, query)}")
        lines.append(f"   {_snippet(record.text)}")
    if not ranked:
        lines.append("(nothing retrieved)")
    return "\n".join(lines) + "\n"


def _why(record: Record, query: set[str]) -> str:
    shared = sorted(set(analyze(record.text, stem=True)) & query)
    if shared:
        return "shares " + ", ".join(shared[:6])
    return "no query word in common; kept beside a closer record"


def _snippet(text: str) -> str:
    flat = redact(" ".join(text.split()))
    if len(flat) <= 160:
        return flat
    return flat[:157].rstrip() + "..."
