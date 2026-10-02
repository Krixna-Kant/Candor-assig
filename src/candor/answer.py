"""Placeholder answers for the retrieval baseline. Wording is not scored yet."""

from __future__ import annotations

from candor.models import Record
from candor.redact import redact


def placeholder(ranked: list[Record]) -> tuple[str, list[str], bool]:
    """A short extract from the top hit, or an abstention when nothing was retrieved."""
    if not ranked:
        return "I don't know.", [], True
    words = redact(ranked[0].text).split()
    return " ".join(words[:40]), [ranked[0].id], False
