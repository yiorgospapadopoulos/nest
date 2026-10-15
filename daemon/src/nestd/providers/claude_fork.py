"""Where a Claude Code conversation is cut to before one of its user messages (B59).

The SDK resumes a conversation up to a transcript entry (`resume_session_at`): the last
entry of the turn that is kept, whatever its type. That is the parent of the user message
the cut drops, which only the transcript file says.
"""

import json
from pathlib import Path
from typing import cast

from nestd.claude_sessions.location import candidate_dirs
from nestd.providers.base import ForkPoint


def fork_point(projects_dir: Path, cwd: Path, session_id: str, message_id: str) -> ForkPoint | None:
    """None when no transcript of `session_id` for `cwd` has the entry `message_id`."""
    for directory in candidate_dirs(projects_dir, cwd):
        found = _parent(directory / f"{session_id}.jsonl", message_id)
        if found is not None:
            return found
    return None


def _parent(path: Path, message_id: str) -> ForkPoint | None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in lines:
        if message_id not in line:
            continue
        try:
            entry: object = json.loads(line)
        except ValueError:
            continue
        if not isinstance(entry, dict):
            continue
        fields = cast("dict[str, object]", entry)
        if fields.get("uuid") == message_id:
            parent = fields.get("parentUuid")
            return ForkPoint(parent if isinstance(parent, str) and parent else None)
    return None
