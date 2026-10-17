"""Concise session titles derived from the user's first prompt."""

import re

MAX_TITLE_LENGTH = 32
MAX_TITLE_WORDS = 6
UNTITLED = "Untitled"
# Shorter results of a line say too little; the next line is tried instead.
_MIN_TITLE_LENGTH = 3

# Words that open a request without saying what it is about, dropped from the start.
_FILLER = re.compile(
    r"^(?:please|kindly|(?:can|could|would|will) (?:you|we|i)|i (?:want|need) you to"
    r"|i(?:['\u2019]d| would) like (?:you )?to|i want(?: to)?|we need to|let['\u2019]?s"
    r"|first(?: of all)?|firstly|now|ok(?:ay)?|so|uh|um|oh|hey|hi|hello|claude|btw|also"
    r"|make it so(?: that)?|go ahead and|help me(?: to)?|try to|there is|this is)"
    r"(?=[\s,.:;!?]|$)[\s,.:;!?]*",
    re.IGNORECASE,
)
# A leading @mention of a pixie or team.
_MENTION = re.compile(r"^@[\w-]+:?\s+")
# "Use (only) the X tool to ..." says how, not what; the request follows it.
_TOOL_LEAD_IN = re.compile(
    r"^use (?:only )?the [\w -]+? (?:tool|subagent)(?: \([^)]*\))? (?:to|and)\s+",
    re.IGNORECASE,
)
_PASTED_TAG = re.compile(r"</?pasted_content[^>]*>")
# Markdown heading, quote and list markers at the start of a line.
_MARKUP = re.compile(r"^[#>*\-\s]+")
# The end of the first clause; common abbreviations are not sentence ends.
_CLAUSE_END = re.compile(
    r"[,;:?!(]|(?<!\be\.g)(?<!\bi\.e)(?<!\betc)(?<!\bvs)\.(?=\s|$)"
    r"|\s(?:and then|then|and|while|so that|because|if|but|in order to)\s",
    re.IGNORECASE,
)
_TRAILING = ".,;:!?-\u2026 "
# Trailing punctuation and words that leave a title hanging.
_DANGLING = re.compile(
    r"(?:[.,;:!?\-\u2026\s]|\s(?:an?|the|to|of|in|on|at|for|with|and|or|as|is|are|that"
    r"|this|my|your|me|it|from|by|so|can|i|what|when|who))+$",
    re.IGNORECASE,
)


def short_title(prompt: str) -> str:
    """The first clause of the first meaningful line, without lead-ins, at most 6 words.

    Lines left too short once lead-ins are dropped are skipped; a prompt of filler alone,
    or too short to lose its last word, keeps it.
    """
    text = _PASTED_TAG.sub("\n", prompt)
    lines = [_MARKUP.sub("", " ".join(line.split())) for line in text.splitlines()]
    for line in lines:
        title = _shorten(_drop_lead_ins(line))
        if len(title) >= _MIN_TITLE_LENGTH:
            return title
    for line in lines:
        if title := _shorten(line, drop_dangling=False):
            return title
    return UNTITLED


def _drop_lead_ins(text: str) -> str:
    previous = None
    while text != previous:
        previous = text
        for lead_in in (_MENTION, _FILLER, _TOOL_LEAD_IN):
            text = lead_in.sub("", text, count=1)
    return text


def _shorten(text: str, *, drop_dangling: bool = True) -> str:
    title = " ".join(_CLAUSE_END.split(text, maxsplit=1)[0].split()[:MAX_TITLE_WORDS])
    while len(title) > MAX_TITLE_LENGTH and " " in title:
        title = title.rsplit(" ", 1)[0]
    title = title[:MAX_TITLE_LENGTH]
    title = _DANGLING.sub("", title) if drop_dangling else title.rstrip(_TRAILING)
    return title[:1].upper() + title[1:]
