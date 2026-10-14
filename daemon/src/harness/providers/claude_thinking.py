"""How long the main agent thought: each thinking block timed from the engine's stream."""

import time
from collections import deque
from collections.abc import Callable
from typing import Any

_THINKING = ("thinking", "redacted_thinking")


class ThinkingTimer:
    """Times thinking blocks from their stream start and stop events (D045).

    A finished block arrives as a whole message, usually after its stop event. Blocks are
    matched to timings in the order they finished; without stream events, a block is timed
    from the previous content (or the input that started the turn).
    """

    def __init__(self, now: Callable[[], float] = time.monotonic) -> None:
        self._now = now
        self._started: dict[int, float] = {}
        self._finished: deque[int] = deque()
        self._last: float | None = None

    def stream(self, event: dict[str, Any]) -> bool | None:
        """Follow a main-agent stream event; True when thinking starts, False when it ends,
        also when a new response drops a block that never ended (BUG-91).
        """
        match event.get("type"):
            case "message_start":
                open_block = bool(self._started)
                self._drop()
                if open_block:
                    return False
            case "content_block_start" if event.get("content_block", {}).get("type") in _THINKING:
                self._started[event.get("index", 0)] = self._now()
                return True
            case "content_block_stop" if event.get("index", 0) in self._started:
                start = self._started.pop(event.get("index", 0))
                self._finished.append(_ms(self._now() - start))
                return False
            case _:
                pass
        return None

    def took(self) -> int | None:
        """The duration of a thinking block that just arrived, in ms; None when unknown."""
        if self._finished:
            return self._finished.popleft()
        if self._started:
            return _ms(self._now() - self._started.pop(min(self._started)))
        return None if self._last is None else _ms(self._now() - self._last)

    def mark(self) -> None:
        """Input was sent or content arrived: a later block without stream timing starts here."""
        self._last = self._now()

    def reset(self) -> None:
        """The turn ended; the next one starts with nothing to match."""
        self._drop()
        self._last = None

    def _drop(self) -> None:
        self._started.clear()
        self._finished.clear()


def _ms(seconds: float) -> int:
    return round(seconds * 1000)
