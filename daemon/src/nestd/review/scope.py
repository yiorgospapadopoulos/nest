"""What a chat's review covers (B160).

A worktree chat's folder is its own, so its review covers all of it. An in-place chat
shares the project folder with the user and other chats, so its review covers only the
paths its own turns changed there, as its file checkpoints record them: other work never
shows in it, keeps it open or gets committed with it. When those paths are not known (an
older chat, a turn that could not be measured, a folder that is not a repository's top)
it covers the whole folder, as before.
"""

from collections.abc import Awaitable, Callable
from pathlib import Path

from nestd.sessions.models import Session

type ChangedPaths = Callable[[str, Path], Awaitable[set[str] | None]]


class ReviewScope:
    def __init__(self, changed_paths: ChangedPaths) -> None:
        self._changed_paths = changed_paths

    async def paths(self, session: Session, cwd: Path) -> set[str] | None:
        """The paths the review of the chat working in `cwd` covers; None for all."""
        if session.mode != "in_place":
            return None
        return await self._changed_paths(session.id, cwd)
