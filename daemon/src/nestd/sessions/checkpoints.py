"""A chat's file checkpoints: a git snapshot of its folder before each user message, on
every engine (B145, D174). The git side is `gitops.snapshots`; this keeps them per chat.

Refs are named `<session id>/<event id>` under `refs/nest/checkpoints/`, so a deleted
chat's go together. A folder that is no git work tree gets none, and a failed snapshot only
costs that message its checkpoint (D048).
"""

import logging
from pathlib import Path

from nestd.gitops import snapshots
from nestd.gitops.runner import GitError
from nestd.providers.base import RewindResult
from nestd.sessions.store import SessionStore

logger = logging.getLogger(__name__)


class FileCheckpoints:
    def __init__(self, store: SessionStore) -> None:
        self._store = store

    async def take(self, session_id: str, event_id: int, folder: Path) -> None:
        """Snapshot `folder` as the checkpoint of the user message `event_id`."""
        try:
            commit = await snapshots.snapshot(folder, f"{session_id}/{event_id}")
        except GitError as error:
            if not error.not_a_repository:
                logger.warning("no file checkpoint for session %s: %s", session_id, error)
            return
        await self._store.save_snapshot(session_id, event_id, commit, folder)

    async def has(self, session_id: str, event_id: int) -> bool:
        return await self._store.snapshot(session_id, event_id) is not None

    async def restore(
        self, session_id: str, event_id: int, folder: Path, dry_run: bool
    ) -> RewindResult:
        """What restoring the chat's `folder` to before the message would change
        (`dry_run`), or what it changed; never raises. The folder is the chat's own: a
        forked worktree chat's snapshots were taken in the original's worktree.
        """
        found = await self._store.snapshot(session_id, event_id)
        if found is None:
            return RewindResult(can_rewind=False, error="no file checkpoint for this message")
        commit, _taken_in = found
        try:
            done = await (snapshots.changes if dry_run else snapshots.restore)(folder, commit)
        except GitError as error:
            return RewindResult(can_rewind=False, error=str(error))
        return RewindResult(
            can_rewind=True,
            files_changed=[str(done.top / change.path) for change in done.changes],
            insertions=done.insertions,
            deletions=done.deletions,
        )

    async def copy(self, source_id: str, source_event: int, session_id: str, event_id: int) -> None:
        """Give a forked chat's copy of a message the original's checkpoint."""
        found = await self._store.snapshot(source_id, source_event)
        if found is None:
            return
        commit, folder = found
        try:
            await snapshots.copy(folder, commit, f"{session_id}/{event_id}")
        except GitError as error:
            logger.warning("the fork %s lost a file checkpoint: %s", session_id, error)
            return
        await self._store.save_snapshot(session_id, event_id, commit, folder)

    @staticmethod
    async def forget(session_id: str, folder: Path) -> None:
        """Delete a deleted chat's snapshot refs from the repository of `folder`."""
        try:
            await snapshots.forget(folder, session_id)
        except GitError as error:
            if not error.not_a_repository:
                logger.warning("the checkpoints of session %s stay: %s", session_id, error)
