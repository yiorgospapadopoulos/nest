"""Which Claude Code chats a running process has open, from `<claude dir>/sessions/<pid>.json`."""

import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import cast

# The entrypoint Claude Code records for runs of the Python Agent SDK, as harness's own.
SDK_ENTRYPOINT = "sdk-py"


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # alive, but another user's
    return True


class LiveChats:
    def __init__(self, claude_dir: Path | None, alive: Callable[[int], bool] = pid_alive) -> None:
        self._dir = None if claude_dir is None else claude_dir / "sessions"
        self._alive = alive

    def running(self) -> dict[str, list[str]]:
        """Session id to the entrypoints of the live processes that have it open."""
        found: dict[str, list[str]] = {}
        for pid, session_id, entrypoint in self._records():
            if pid > 0 and self._alive(pid):
                found.setdefault(session_id, []).append(entrypoint)
        return found

    def open_elsewhere(self, session_id: str, own_run: bool) -> bool:
        """Whether a process other than harness's own run has the chat open.

        While harness runs the session itself, its SDK process is one of them; Claude Code
        in a terminal, the desktop app or an editor is not.
        """
        return any(
            not (own_run and entrypoint == SDK_ENTRYPOINT)
            for entrypoint in self.running().get(session_id, [])
        )

    def _records(self) -> list[tuple[int, str, str]]:
        if self._dir is None:
            return []
        files = sorted(self._dir.glob("*.json"))
        records: list[tuple[int, str, str]] = []
        for file in files:
            if not file.stem.isdigit():
                continue
            try:
                value: object = json.loads(file.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(value, dict):
                continue
            data = cast("dict[str, object]", value)
            pid, session_id, entrypoint = (
                data.get("pid"),
                data.get("sessionId"),
                data.get("entrypoint"),
            )
            if isinstance(pid, int) and isinstance(session_id, str):
                records.append((pid, session_id, entrypoint if isinstance(entrypoint, str) else ""))
        return records
