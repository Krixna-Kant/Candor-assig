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
    return [record for _score, record in scored(records, query, stem=stem, windows=False)[:limit]]


def scored(records: list[Record], query: str, *, stem: bool, windows: bool) -> list[tuple[float, Record]]:
    """Every matching record and its BM25 score, best first.

    Long units are scored on their best token window so one Codex session does not
    lose to a short segment only because of length. The id stays the unit id.
    """
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
    lengths = [min(len(tokens), 160) or 1 for _record, tokens in docs]
    average_length = sum(lengths) / count
    query_counts = Counter(query_terms)
    ranked: list[tuple[float, int, int, Record]] = []
    for index, (record, tokens) in enumerate(docs):
        score, matched = _best_score(tokens, query_counts, document_frequency, count, average_length, windows)
        if matched:
            ranked.append((score, matched, index, record))
    ranked.sort(key=lambda item: (-item[0], -item[1], item[2]))
    return [(score, record) for score, _matched, _index, record in ranked]


def _best_score(tokens, query_counts, document_frequency, count, average_length, windows: bool) -> tuple[float, int]:
    if not tokens:
        return 0.0, 0
    if not windows or len(tokens) <= 160:
        return _score_tokens(tokens, query_counts, document_frequency, count, average_length)
    size = 80
    step = 40
    best = (0.0, 0)
    for start in range(0, len(tokens) - size + 1, step):
        candidate = _score_tokens(tokens[start:start + size], query_counts, document_frequency, count, average_length)
        if candidate[0] > best[0]:
            best = candidate
    return best


def _score_tokens(tokens, query_counts, document_frequency, count, average_length) -> tuple[float, int]:
    term_frequency = Counter(tokens)
    length = len(tokens) or 1
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
    return score, matched
