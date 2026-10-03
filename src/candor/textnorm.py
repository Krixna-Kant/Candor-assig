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

# All-caps tokens that are ordinary words or SQL, not abbreviations.
_NOT_ACRONYM = _STOP | frozenset({
    "and", "or", "not", "by", "from", "where", "select", "order", "null", "group",
    "create", "index", "over", "weekly", "range", "as", "on", "pm", "us",
})
_ACRONYMS: set[str] = set()
_SHORT: set[str] = set()


def learn_lexicon(texts) -> None:
    """Acronyms and short tokens attested in the corpus. Query expansion uses only these."""
    acronyms: set[str] = set()
    short: set[str] = set()
    for text in texts:
        for match in re.finditer(r"\b[A-Z]{2,5}\b", text):
            word = match.group(0).lower()
            if word not in _NOT_ACRONYM:
                acronyms.add(word)
        for token in tokenize(text):
            if token.isalpha() and 4 <= len(token) <= 6:
                short.add(token)
    global _ACRONYMS, _SHORT
    _ACRONYMS = acronyms
    _SHORT = short


def analyze(text: str, *, stem: bool, expand: bool = False) -> list[str]:
    """Tokens for BM25. `stem=True` also applies the synonym table.

    `expand=True` is for the query only. A phrase whose initials match an acronym
    attested in the corpus gains that acronym. A long word gains a shorter corpus
    token when that token is a prefix, so "preparation" can meet "prep".
    """
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
    if expand:
        analyzed.extend(_initialisms(tokens))
        analyzed.extend(_clips(tokens))
    return analyzed


def _initialisms(tokens: list[str]) -> list[str]:
    pieces: list[str] = []
    for token in tokens:
        for part in re.split(r"[-/]", token):
            if part.isalpha() and len(part) >= 2:
                pieces.append(part)
    found: list[str] = []
    for size in range(2, 5):
        for start in range(0, len(pieces) - size + 1):
            window = pieces[start:start + size]
            if all(part in _STOP for part in window):
                continue
            acronym = "".join(part[0] for part in window)
            if acronym in _ACRONYMS:
                found.append(acronym)
    return found


def _clips(tokens: list[str]) -> list[str]:
    found: list[str] = []
    for token in tokens:
        if not token.isalpha() or len(token) < 8:
            continue
        for length in range(6, 3, -1):
            short = token[:length]
            if short in _SHORT and short not in _STOP and len(token) - length >= 3:
                found.append(short)
                break
    return found
