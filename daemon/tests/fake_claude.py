"""Stands in for every `claude` command line run, so no test reaches the real CLI."""

import asyncio
from collections.abc import Sequence
from pathlib import Path

from nestd.claude_code.cli import ClaudeLocations
from nestd.gitops.runner import CommandError

type Reply = str | BaseException


class FakeClaude:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []
        # Replies by the arguments after the program, used in order; the last one stays.
        self.replies: dict[tuple[str, ...], list[Reply]] = {}
        # Runs whose arguments are here wait until the event is set.
        self.gates: dict[tuple[str, ...], asyncio.Event] = {}

    def script(self, *args: str, reply: Reply = "") -> None:
        self.replies.setdefault(tuple(args), []).append(reply)

    def args_of(self, program: str | Path) -> list[tuple[str, ...]]:
        return [call[1:] for call in self.calls if call[0] == str(program)]

    async def __call__(self, argv: Sequence[str], cwd: Path) -> str:
        self.calls.append(tuple(argv))
        args = tuple(argv[1:])
        gate = self.gates.get(args)
        if gate is not None:
            await gate.wait()
        queue = self.replies.get(args)
        if not queue:
            raise CommandError(argv, 1, f"unscripted: {' '.join(args)}\n")
        reply = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(reply, BaseException):
            raise reply
        return reply


def locations(tmp_path: Path) -> ClaudeLocations:
    """No standalone Claude Code; the bundled one is a file in `tmp_path`."""
    bundled = tmp_path / "sdk" / "claude"
    return ClaudeLocations(
        search_path="",
        candidates=(tmp_path / "home" / ".local" / "bin" / "claude",),
        bundled=bundled,
        bundled_version="2.1.286",
    )


def install_standalone(where: ClaudeLocations) -> Path:
    """Put an executable file where the first candidate is."""
    path = where.candidates[0]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n", encoding="utf-8")
    path.chmod(0o755)
    return path
