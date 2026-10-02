"""Okapi BM25 over an in-memory set of units. Ties keep input order."""

from __future__ import annotations

import math
from collections import Counter

from candor.models import Record
from candor.textnorm import analyze

K1 = 1.5
B = 0.75


def rank(records: list[Record], query: str, *, stem: bool, limit: int = 20) -> list[Record]:
    """Return up to `limit` records, best first. The input must already be time-filtered."""
    if not records:
        return []
    docs = [(record, analyze(record.text, stem=stem)) for record in records]
    query_terms = analyze(query, stem=stem)
    if not query_terms:
        return []
    count = len(docs)
    document_frequency: Counter[str] = Counter()
    for _record, tokens in docs:
        document_frequency.update(set(tokens))
    average_length = sum(len(tokens) for _record, tokens in docs) / count
    query_counts = Counter(query_terms)
    scored: list[tuple[float, int, int, Record]] = []
    for index, (record, tokens) in enumerate(docs):
        if not tokens:
            continue
        term_frequency = Counter(tokens)
        length = len(tokens)
        score = 0.0
        matched = 0
        for term, repeats in query_counts.items():
            freq = term_frequency.get(term)
            if not freq:
                continue
            matched += 1
            df = document_frequency[term]
            idf = math.log(1.0 + (count - df + 0.5) / (df + 0.5))
            denominator = freq + K1 * (1.0 - B + B * length / average_length)
            score += repeats * idf * (freq * (K1 + 1.0)) / denominator
        if matched:
            scored.append((score, matched, index, record))
    scored.sort(key=lambda item: (-item[0], -item[1], item[2]))
    return [item[3] for item in scored[:limit]]
