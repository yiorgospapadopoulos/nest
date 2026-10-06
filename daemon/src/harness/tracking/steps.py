"""Short, single-line descriptions of tool calls and results for activity displays."""

import re
from pathlib import PurePosixPath

from pydantic import JsonValue

MAX_LENGTH = 80
# The input field that best describes a call, in order of preference.
_ARG_KEYS = (
    "command",
    "file_path",
    "notebook_path",
    "pattern",
    "path",
    "url",
    "query",
    "subject",
    "description",
    "taskId",
    "prompt",
)
_WHITESPACE = re.compile(r"\s+")


def short_arg(tool_input: dict[str, JsonValue], root: str | None) -> str:
    for key in _ARG_KEYS:
        value = tool_input.get(key)
        if isinstance(value, str | int) and not isinstance(value, bool) and value != "":
            return one_line(_relative(str(value), root))
    return ""


def short_result(content: str, is_error: bool) -> str:
    text = one_line(content)
    return f"error: {text}" if is_error else text


def _relative(value: str, root: str | None) -> str:
    """Paths inside the session's working directory are shown relative to it."""
    if root is None:
        return value
    path = PurePosixPath(value)
    return str(path.relative_to(root)) if path.is_relative_to(root) else value


def one_line(text: str, limit: int = MAX_LENGTH) -> str:
    """The first non-blank line, whitespace collapsed, cut to `limit` characters."""
    line = next((line for line in text.splitlines() if line.strip()), "")
    line = _WHITESPACE.sub(" ", line).strip()
    return line if len(line) <= limit else line[: limit - 1] + "…"
