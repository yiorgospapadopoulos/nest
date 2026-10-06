"""A command runner standing in for macOS `open`, so tests never launch apps."""

from collections.abc import Sequence
from pathlib import Path


class FakeOpener:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[str, ...], Path]] = []
        self.failure: Exception | None = None

    async def __call__(self, argv: Sequence[str], cwd: Path) -> str:
        self.calls.append((tuple(argv), cwd))
        if self.failure is not None:
            raise self.failure
        return ""
