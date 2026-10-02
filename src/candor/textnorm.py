"""Tokenizer, a Porter step-1 stemmer, and a small domain synonym table.

Plain BM25 uses `analyze(..., stem=False)`. The second ranker stems, then maps
a few inflected variants onto one token (`moved` and `slipped` both become `slip`).
Numbers, dates, amounts, and ids are left intact.
"""

from __future__ import annotations

import re

_TOKEN = re.compile(r"[a-z0-9]+(?:[./'#:_\-][a-z0-9]+)*", re.IGNORECASE)
_STOP = frozenset({
    "a", "an", "the", "of", "to", "and", "in", "on", "for", "is", "it", "that",
    "this", "with", "as", "at", "by", "from", "or", "be", "are", "was", "were",
    "what", "when", "who", "how", "which", "did", "do", "does", "my", "me", "i",
    "we", "our", "you", "your",
})
_VOWELS = set("aeiou")

# Head word -> surface forms. Applied after stemming, so the table keys are stems.
_GROUPS = {
    "slip": ["slip", "move", "push", "delay", "reschedule"],
    "launch": ["launch", "ship", "golive"],
    "owe": ["owe", "promise"],
    "own": ["own", "assign"],
    "cancel": ["cancel"],
    "sign": ["sign"],
    "propose": ["propose", "proposal", "proposed"],
    "flight": ["fly", "flight", "flying"],
    "dictate": ["dictate", "dictation", "dictated"],
    "contract": ["contract", "agreement"],
}


def tokenize(text: str) -> list[str]:
    """Split text into lowercase tokens, keeping dates, amounts, and ids whole."""
    lowered = text.lower().replace("go-live", "golive").replace("go live", "golive")
    tokens = []
    for match in _TOKEN.finditer(lowered):
        token = match.group(0)
        if token in _STOP:
            continue
        if len(token) == 1 and not token.isdigit():
            continue
        tokens.append(token)
    return tokens


def _is_consonant(word: str, index: int) -> bool:
    char = word[index]
    if char in _VOWELS:
        return False
    if char == "y":
        if index == 0:
            return True
        return not _is_consonant(word, index - 1)
    return True


def _measure(word: str) -> int:
    measure = 0
    index = 0
    length = len(word)
    while index < length and _is_consonant(word, index):
        index += 1
    while index < length:
        while index < length and not _is_consonant(word, index):
            index += 1
        if index >= length:
            break
        measure += 1
        while index < length and _is_consonant(word, index):
            index += 1
    return measure


def _has_vowel(word: str) -> bool:
    return any(not _is_consonant(word, index) for index in range(len(word)))


def _double_consonant(word: str) -> bool:
    return len(word) >= 2 and word[-1] == word[-2] and _is_consonant(word, len(word) - 1)


def _cvc(word: str) -> bool:
    if len(word) < 3 or word[-1] in "wxy":
        return False
    last = len(word) - 1
    return _is_consonant(word, last) and not _is_consonant(word, last - 1) and _is_consonant(word, last - 2)


def _restore(stem: str) -> str:
    if stem.endswith(("at", "bl", "iz")):
        return stem + "e"
    if _double_consonant(stem) and stem[-1] not in "lsz":
        return stem[:-1]
    if _measure(stem) == 1 and _cvc(stem):
        return stem + "e"
    return stem


def stem_token(word: str) -> str:
    """Porter step 1, enough to join slip/slipped and move/moved. Digits stay put."""
    if len(word) <= 2 or any(char.isdigit() for char in word):
        return word
    if word.endswith("sses"):
        word = word[:-2]
    elif word.endswith("ies"):
        word = word[:-2]
    elif word.endswith("ss"):
        pass
    elif word.endswith("s") and len(word) > 3:
        word = word[:-1]
    if word.endswith("eed"):
        stem = word[:-3]
        if _measure(stem) > 0:
            word = stem + "ee"
    elif word.endswith("ed") and _has_vowel(word[:-2]):
        word = _restore(word[:-2])
    elif word.endswith("ing") and _has_vowel(word[:-3]):
        word = _restore(word[:-3])
    return word


def _synonym_table() -> dict[str, str]:
    table: dict[str, str] = {}
    for canonical, words in _GROUPS.items():
        head = stem_token(canonical)
        for word in words:
            table[stem_token(word)] = head
    return table


_SYNONYMS = _synonym_table()


def analyze(text: str, *, stem: bool) -> list[str]:
    """Tokens for BM25. `stem=True` also applies the synonym table."""
    tokens = tokenize(text)
    if not stem:
        return tokens
    analyzed = []
    for token in tokens:
        if any(char.isdigit() for char in token):
            analyzed.append(token)
            continue
        stemmed = stem_token(token)
        analyzed.append(_SYNONYMS.get(stemmed, stemmed))
    return analyzed
