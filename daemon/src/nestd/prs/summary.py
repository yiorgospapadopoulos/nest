"""A short description of a pull request Nest opens, made without a model call (D034)."""

import re

from nestd.review.models import DiffStats
from nestd.tracking.steps import one_line

MAX_SUMMARY_LINES = 2
MAX_LINE_LENGTH = 120
# Markdown that only decorates a line: headings, bullets, quotes and numbering.
_LEADING_MARKUP = re.compile(r"^\s*(?:[#>*+-]+|\d+[.)])(?:\s+|$)")


def pr_summary(text: str | None, stats: DiffStats) -> str:
    """Up to two lines of the agent's final summary, then the diff stats."""
    lines = [_plain(line) for line in (text or "").splitlines()]
    kept = [one_line(line, MAX_LINE_LENGTH) for line in lines if line][:MAX_SUMMARY_LINES]
    files = "1 file" if stats.files == 1 else f"{stats.files} files"
    return "\n".join([*kept, f"{files} changed, +{stats.additions} -{stats.deletions}"])


def _plain(line: str) -> str:
    return _LEADING_MARKUP.sub("", line).replace("**", "").replace("`", "").strip()
