"""A fake Claude Code data dir (`~/.claude`) in a temporary folder, with chat builders."""

import json
import os
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path

from harness.claude_sessions.location import encode_folder

type Entry = Mapping[str, object]

CHAT_A = "aaaaaaaa-0000-4000-8000-000000000001"
CHAT_B = "bbbbbbbb-0000-4000-8000-000000000002"
CHAT_C = "cccccccc-0000-4000-8000-000000000003"


class ClaudeHome:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.projects = root / "projects"
        self.sessions = root / "sessions"

    def project_dir(self, cwd: Path) -> Path:
        return self.projects / encode_folder(cwd)

    def write_chat(
        self,
        cwd: Path,
        chat_id: str,
        entries: Sequence[Entry],
        modified: datetime | None = None,
        directory: Path | None = None,
    ) -> Path:
        """Entries get the chat's cwd and session id unless they set their own."""
        folder = directory or self.project_dir(cwd)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{chat_id}.jsonl"
        lines = [json.dumps({"cwd": str(cwd), "sessionId": chat_id, **entry}) for entry in entries]
        path.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")
        if modified is not None:
            os.utime(path, (modified.timestamp(), modified.timestamp()))
        return path

    def open_chat(
        self, pid: int, chat_id: str, entrypoint: str = "cli", status: str | None = None
    ) -> Path:
        """A sessions file, as a running Claude Code process writes it."""
        self.sessions.mkdir(parents=True, exist_ok=True)
        path = self.sessions / f"{pid}.json"
        record = {"pid": pid, "sessionId": chat_id, "cwd": "/x", "entrypoint": entrypoint}
        if status is not None:
            record["status"] = status
        path.write_text(json.dumps(record), encoding="utf-8")
        return path


def user(uuid: str, content: object, parent: str | None = None, **extra: object) -> Entry:
    return {
        "type": "user",
        "uuid": uuid,
        "parentUuid": parent,
        "isSidechain": False,
        "timestamp": "2026-10-05T09:00:00Z",
        "message": {"role": "user", "content": content},
        **extra,
    }


def assistant(uuid: str, blocks: list[object], parent: str | None, **extra: object) -> Entry:
    return {
        "type": "assistant",
        "uuid": uuid,
        "parentUuid": parent,
        "isSidechain": False,
        "timestamp": "2026-10-05T09:01:00Z",
        "message": {"role": "assistant", "content": blocks},
        **extra,
    }


def text(value: str) -> Entry:
    return {"type": "text", "text": value}


def simple_chat(prompt: str = "Fix the login bug. It fails", reply: str = "Fixed.") -> list[Entry]:
    return [user("u1", prompt), assistant("a1", [text(reply)], "u1")]
