"""A chat's file checkpoints: a git snapshot of its folder before each user message, on
every engine (B145, D174). The git side is `gitops.snapshots`; this keeps them per chat.

Refs are named `<session id>/<event id>` under `refs/nest/checkpoints/`, so a deleted
chat's go together. A folder that is no git work tree's top gets none, and a failed snapshot
only costs that message its checkpoint (D048).

Each checkpoint also records the paths the chat's own turns changed after it: from the
snapshot to the turn's end, and in a later turn the agent starts on its own. A rewind puts
back only those, so what other chats, the user or a pull changed between the turns stays.
Where a running turn's work is measured from is kept in the database, so a turn cut off by
a restart gets its paths when Nest starts again. A checkpoint whose paths are not known (an
older one, or a turn that could not be measured) restores the whole folder, as before
(B159 R10).
"""

import logging
from pathlib import Path

from nestd.gitops import snapshots
from nestd.gitops.runner import GitError
from nestd.providers.base import RewindResult
from nestd.sessions.bookkeeping import isolated
from nestd.sessions.models import TurnMark
from nestd.sessions.store import SessionStore

logger = logging.getLogger(__name__)


class FileCheckpoints:
    def __init__(self, store: SessionStore) -> None:
        self._store = store

    async def take(
        self, session_id: str, event_id: int, folder: Path, *, in_turn: bool = False
    ) -> None:
        """Snapshot `folder` as the checkpoint of the user message `event_id`. What the
        running turn (a message written into it, `in_turn`) or one that never ended did so
        far is recorded first.
        """
        await self.turn_ended(session_id)
        try:
            commit = await snapshots.snapshot(folder, f"{session_id}/{event_id}")
        except snapshots.NotTheTopError:
            return
        except GitError as error:
            if not error.not_a_repository:
                logger.warning("no file checkpoint for session %s: %s", session_id, error)
                # This message's turn counts for the latest checkpoint, unmeasured.
                latest = await self._store.latest_snapshot(session_id)
                if latest is not None:
                    await self._store.forget_snapshot_paths(session_id, latest)
            return
        await self._store.save_snapshot(session_id, event_id, commit, folder)
        await self._store.set_turn_mark(
            session_id, TurnMark(event_id=event_id, commit=commit, folder=folder, first=True)
        )

    async def turn_started(self, session_id: str, folder: Path) -> None:
        """The agent started a turn on its own: its work counts for the latest checkpoint."""
        if await self._store.has_turn_mark(session_id):
            return
        event_id = await self._store.latest_snapshot(session_id)
        if event_id is None:
            return
        try:
            commit = await snapshots.state(folder)
        except GitError as error:
            logger.warning("session %s's own turn goes unmeasured: %s", session_id, error)
            await self._store.forget_snapshot_paths(session_id, event_id)
            return
        mark = TurnMark(event_id=event_id, commit=commit, folder=folder, first=False)
        await self._store.set_turn_mark(session_id, mark)

    async def turn_ended(self, session_id: str) -> None:
        """Record the paths the turn changed since its mark."""
        mark = await self._store.take_turn_mark(session_id)
        if mark is None:
            return
        try:
            paths = await snapshots.changed_since(mark.folder, mark.commit)
        except GitError as error:
            logger.warning("session %s's turn goes unmeasured: %s", session_id, error)
            await self._store.forget_snapshot_paths(session_id, mark.event_id)
            return
        await self._store.add_snapshot_paths(session_id, mark.event_id, paths, first=mark.first)

    async def turns_cut_off(self) -> None:
        """On start: record the paths of the turns a previous process left running."""
        for session_id in await self._store.sessions_with_turn_marks():
            await isolated(
                "the cut-off turn's changed files", session_id, self.turn_ended(session_id)
            )

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
        only = await self._store.snapshot_paths(session_id, event_id)
        try:
            done = await (snapshots.changes if dry_run else snapshots.restore)(folder, commit, only)
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
        paths = await self._store.snapshot_paths_of(source_id, source_event)
        await self._store.save_snapshot(session_id, event_id, commit, folder, paths)

    @staticmethod
    async def forget(session_id: str, folder: Path) -> None:
        """Delete a deleted chat's snapshot refs from the repository of `folder`."""
        try:
            await snapshots.forget(folder, session_id)
        except GitError as error:
            if not error.not_a_repository:
                logger.warning("the checkpoints of session %s stay: %s", session_id, error)
