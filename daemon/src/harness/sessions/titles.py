"""Concise session titles derived from the user's first prompt."""

import re

MAX_TITLE_LENGTH = 48
UNTITLED = "Untitled"

# Words that open a request without saying what it is about, dropped from the start.
_FILLER = re.compile(
    r"^(?:please|kindly|(?:can|could|would|will) you|i (?:want|need) you to"
    r"|i(?:['\u2019]d| would) like you to|i want to|we need to|let['\u2019]?s"
    r"|first(?: of all)?|firstly|now|ok(?:ay)?|so|hey|hi|hello|claude)"
    r"(?=[\s,.:;!?]|$)[\s,.:;!?]*",
    re.IGNORECASE,
)
# Markdown heading, quote and list markers at the start of a line.
_MARKUP = re.compile(r"^[#>*\-\s]+")
# The end of the first sentence; common abbreviations are not sentence ends.
_SENTENCE_END = re.compile(
    r"(?<!\be\.g)(?<!\bi\.e)(?<!\betc)(?<!\bvs)[.!?]+(?=\s|$)", re.IGNORECASE
)
_TRAILING = ".,;:!?-… "


def short_title(prompt: str) -> str:
    """The first sentence of the first meaningful line, without filler, at most 48 chars.

    Lines left empty once filler is dropped are skipped; a prompt of filler alone keeps it.
    """
    lines = [_MARKUP.sub("", " ".join(line.split())) for line in prompt.splitlines()]
    for text in (*map(_drop_filler, lines), *lines):
        title = _shorten(text)
        if title:
            return title
    return UNTITLED


def _drop_filler(text: str) -> str:
    while match := _FILLER.match(text):
        text = text[match.end() :]
    return text


def _shorten(text: str) -> str:
    sentence = _SENTENCE_END.split(text, maxsplit=1)[0]
    if len(sentence) > MAX_TITLE_LENGTH:
        cut = sentence[: MAX_TITLE_LENGTH + 1]
        sentence = cut.rsplit(" ", 1)[0] if " " in cut else cut[:MAX_TITLE_LENGTH]
    sentence = sentence.rstrip(_TRAILING)
    return sentence[:1].upper() + sentence[1:]
