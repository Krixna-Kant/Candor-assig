"""Planted instructions stay in the index and rank below ordinary evidence."""

from __future__ import annotations

import re

from candor.models import Record

_INJECTION = re.compile(
    r"ignore (?:all |your |previous )?instructions|note to any .{0,40}assistant|<!--",
    re.IGNORECASE,
)
_ABOUT = re.compile(r"\b(digest|newsletter|promo|instruction)\b", re.IGNORECASE)


def is_untrusted(record: Record) -> bool:
    """True when the text tells a model to ignore its task or hide an instruction."""
    return _INJECTION.search(record.text) is not None


def question_is_about_untrusted(question: str) -> bool:
    """A question that asks about the message itself can still surface it."""
    return _ABOUT.search(question) is not None
