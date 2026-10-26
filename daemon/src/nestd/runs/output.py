"""A run's recent output: the last lines, raw (B108)."""

import codecs
from collections import deque

MAX_LINES = 2000


class OutputBuffer:
    """The last `max_lines` lines of a run's output, terminal escapes included. Bytes are
    decoded as UTF-8, a character split between two reads included; what is not UTF-8
    reads as the replacement character.
    """

    def __init__(self, max_lines: int = MAX_LINES) -> None:
        self._max_lines = max_lines
        self._lines: deque[str] = deque(maxlen=max_lines)
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")

    def clear(self) -> None:
        self._lines.clear()
        self._decoder.reset()

    def add(self, data: bytes) -> str:
        """Add a chunk as read; returns its text, which may end mid-line."""
        text = self._decoder.decode(data)
        self.add_text(text)
        return text

    def add_text(self, text: str) -> None:
        if not text:
            return
        # The last line goes on while it has no newline yet.
        if self._lines and not self._lines[-1].endswith("\n"):
            text = self._lines.pop() + text
        parts = text.split("\n")
        lines = [f"{part}\n" for part in parts[:-1]]
        if parts[-1]:
            lines.append(parts[-1])
        self._lines.extend(lines)

    def text(self) -> str:
        return "".join(self._lines)
