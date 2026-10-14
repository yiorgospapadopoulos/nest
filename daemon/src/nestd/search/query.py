"""Turns what the user typed into an FTS5 query that can never be a syntax error.

Every word becomes a quoted string, so FTS operators (AND, OR, NOT, NEAR, column filters,
parentheses) are searched as plain words. `"two words"` is a phrase and `word*` a prefix.
"""

import re

MAX_TERMS = 16
# A quoted phrase (the closing quote may be missing) or a run of other characters.
_TOKEN = re.compile(r'"([^"]*)"?|([^\s"]+)')


def fts_query(text: str) -> str | None:
    """The FTS5 query for `text`, or None when it holds no word to search for."""
    terms: list[str] = []
    for match in _TOKEN.finditer(text):
        phrase, word = match.group(1), match.group(2)
        if phrase is not None:
            term = _quoted(phrase) if _has_word(phrase) else None
        else:
            core = word.rstrip("*")
            prefix = "*" if core != word else ""
            term = _quoted(core) + prefix if _has_word(core) else None
        if term is not None:
            terms.append(term)
    return " ".join(terms[:MAX_TERMS]) or None


def _has_word(text: str) -> bool:
    return any(char.isalnum() for char in text)


def _quoted(text: str) -> str:
    # Tokens never contain a double quote, so nothing needs escaping inside the string.
    return '"' + " ".join(text.split()) + '"'
