"""Text from GitHub for the agent: CI logs, issues and review comments (SEC-19, SEC-20).

Such text can hold anything, so it goes to the agent without escape sequences, control
characters or anything that looks like a credential, in a code block it cannot close.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass

from nestd.gitops.remotes import scrub_credentials

# What ends a block's text that was cut to fit, and the least of a text worth sending cut.
CUT_MARK = "\n[...]"
MIN_CUT_CHARS = 200
# Terminal escape sequences, in 7-bit (ESC) and 8-bit (C1) forms: control sequences (CSI),
# strings such as titles and hyperlinks (OSC, DCS, PM, APC; one never ended runs to the end
# of the line), then any other ESC sequence such as a charset choice.
_ESCAPES = re.compile(
    r"(?:\x1b\[|\x9b)[0-?]*[ -/]*[@-~]"
    r"|(?:\x1b[\]P^_X]|[\x90\x98\x9d\x9e\x9f])[^\x07\x1b\x9c\n]*(?:\x07|\x1b\\|\x9c)?"
    r"|\x1b[ -/]*[0-~]?"
)
# What is left of the C0 and C1 control characters, except tab and newline.
_CONTROLS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")
# Known token formats, matched anywhere, even glued to a name such as GH_TOKENghp_...:
# GitHub (classic, OAuth, user-to-server, server-to-server, refresh, fine-grained), npm,
# and AWS access key ids.
_TOKENS = re.compile(
    r"gh[opusr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|npm_[A-Za-z0-9]{30,}"
    r"|(?:AKIA|ASIA)[A-Z0-9]{16}"
)
# Values of credential headers and assignments: `Authorization: Bearer <value>`,
# `aws_secret_access_key = <value>`, `MY_API_TOKEN=<value>`, `password: '<value>'`.
# A name is matched from its start only: trying every position inside a long run of
# letters took time quadratic in its length (a 30 000 letter issue body took a minute).
_ASSIGNED = re.compile(
    r"""(?ix)
    (
        (?:proxy-)?authorization["']?\s*[:=]\s*["']?(?:(?:bearer|basic|token)\s+)?
        | (?<![a-z0-9_.-])[a-z0-9_.-]*
          (?:token|secret|password|passwd|api_?key|access_key)["']?\s*[:=]\s*["']?
    )
    [^\s"',;]+
    """
)


def clean(text: str) -> str:
    """`text` without escape sequences, control characters (but tab and newline) and
    credentials. Clean a whole text before cutting it, so no cut leaves part of a secret.
    """
    text = _CONTROLS.sub("", _ESCAPES.sub("", text))
    text = _ASSIGNED.sub(r"\1***", scrub_credentials(text))
    return _TOKENS.sub("***", text)


def one_line(text: str) -> str:
    """Cleaned, on one line: for titles, labels, names and paths."""
    return " ".join(clean(text).split())


def fenced(body: str) -> str:
    """`body` in a code block whose fence is longer than any run of backticks in it."""
    longest = max((len(ticks) for ticks in re.findall(r"`+", body)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}\n{body}\n{fence}"


@dataclass(frozen=True)
class Block:
    """Cleaned untrusted text for a code block, under a heading line of Nest's."""

    heading: str
    text: str


def fit_blocks(blocks: Sequence[Block], budget: int) -> tuple[list[str], int]:
    """Each block as its heading over its fenced text, in order, while they fit in
    `budget` characters with a blank line between them. The first that does not fit is
    cut when enough of it fits, and the rest are left out. Returns the parts and how many
    blocks went whole.
    """
    parts: list[str] = []
    used = 0
    for whole, block in enumerate(blocks):
        gap = 2 if parts else 0
        part = _block(block.heading, block.text)
        if used + gap + len(part) <= budget:
            parts.append(part)
            used += gap + len(part)
            continue
        fence = len(fenced(block.text).split("\n", 1)[0])
        frame = len(block.heading) + 1 + 2 * (fence + 1)
        room = budget - used - gap - frame - len(CUT_MARK)
        if room >= MIN_CUT_CHARS:
            parts.append(_block(block.heading, block.text[:room] + CUT_MARK))
        return parts, whole
    return parts, len(blocks)


def _block(heading: str, text: str) -> str:
    return f"{heading}\n{fenced(text)}"
