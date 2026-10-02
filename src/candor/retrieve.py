"""Rank units that exist at `as_of`. Later and deleted records never enter BM25."""

from __future__ import annotations

from datetime import datetime

from candor.bm25 import rank
from candor.models import Corpus, Record
from candor.timeline import visible


def retrieve(corpus: Corpus, question: str, as_of: datetime, *, stem: bool, limit: int = 20) -> list[Record]:
    """Best-first list of units visible at `as_of`."""
    return rank(visible(corpus, as_of), question, stem=stem, limit=limit)
