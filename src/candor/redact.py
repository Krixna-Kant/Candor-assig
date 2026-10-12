"""Strip key-shaped strings from anything we write out."""

from __future__ import annotations

import re

_KEY = re.compile(r"\b(?:sk-|gsk_)[A-Za-z0-9_\-]{16,}|\bAIza[0-9A-Za-z_\-]{30,}")


def redact(text: str) -> str:
    """Replace key-shaped tokens. The pattern is the only thing this function knows."""
    return _KEY.sub("[REDACTED]", text)


def has_key_shape(text: str) -> bool:
    return _KEY.search(text) is not None
