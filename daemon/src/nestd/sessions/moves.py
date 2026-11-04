"""A chat moves between worktrees (B119): where it works can change any number of times.

The chat's tool only records a change, in the session row: removing the folder an agent
works in closes its run, which would cut off its reply. The change applies when the turn
ends normally, or when a message cuts it short to go next, before that message starts, so
the next message opens a run in the new folder that resumes the same conversation. A Stop
or a failed turn cancels it and the agent hears so with its next message. After a daemon
restart the recorded change is applied, as nothing else can happen to it. A change that
fails leaves the chat where it is, working, and says why in the chat and to the agent.

Judging whether a worktree's work is merged is the agent's job, with git, when the user
asks; Nest removes what it is told to. It keeps its own rules: a worktree another open
chat uses stays, only its own worktrees are removed, and the branch always stays.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path

from pydantic import JsonValue

from nestd.approvals.models import ApprovalKind
from nestd.approvals.queue import ApprovalQueue
from nestd.clock import Clock
from nestd.config.models import RepoConfig
from nestd.errors import ConflictError, NestError
from nestd.events import types
from nestd.events.bus import EventBus
from nestd.gitops.runner import CommandError, GitError
from nestd.repos.branch_map import Checkout, checkouts
from nestd.repos.service import RepoService
from nestd.sessions.bookkeeping import isolated
from nestd.sessions.hooks import SessionHooks
from nestd.sessions.joining import Place, join_worktree
from nestd.sessions.live import LiveSession
from nestd.sessions.models import (
    EarlierState,
    EarlierWorktree,
    PendingWorktree,
    Session,
    WorktreeChange,
)
from nestd.sessions.rules import among, require_open
from nestd.sessions.store import SessionStore
from nestd.sessions.subagents import CallBridge
from nestd.sessions.updates import announce_changes
from nestd.sessions.workspace import run_setup, uninterrupted, workspace_payload
from nestd.worktrees.manager import Worktree, WorktreeManager
from nestd.worktrees.setup import LinkResult

logger = logging.getLogger(__name__)

# What the tool calls the project folder.
PROJECT = "project"
CHANGED: str = "worktree_changed"
FAILED: str = "worktree_failed"
_STOPPED = "the turn stopped before it ended"
# What belonged to the branch the chat left. A pull request it goes back to is found again
# when its next turn ends (`PrAdopter`).
_LEFT_BEHIND: dict[str, object] = {
    "pr_url": None,
    "pr": None,
    "pr_summary": None,
    "review": None,
    "commit_sha": None,
}

# Removes the worktree unless Nest did not make it or another open chat uses it.
type RemoveWorktree = Callable[[RepoConfig, Session, Worktree], Awaitable[bool]]
type BackgroundRunning = Callable[[str], bool]


class MoveRefusedError(ConflictError):
    """The change cannot be made; its text goes to the agent as it is."""


class WorktreeMoves:
    def __init__(
        self,
        *,
        store: SessionStore,
        bus: EventBus,
        repos: RepoService,
        worktrees: WorktreeManager,
        approvals: ApprovalQueue,
        hooks: SessionHooks,
        clock: Clock,
        remove: RemoveWorktree,
        background: BackgroundRunning,
    ) -> None:
        """`background` says whether the chat's agent has background tasks running, which
        end with its run.
        """
        self._store = store
        self._bus = bus
        self._repos = repos
        self._worktrees = worktrees
        self._approvals = approvals
        self._hooks = hooks
        self._clock = clock
        self._remove_worktree = remove
        self._background = background
        # The pixies runs call with call_pixie (B112), which work in the chat's folder.
        self.bridge: CallBridge | None = None

    async def listing(self, session_id: str) -> str:
        """The project's worktrees and who works in them, for the agent."""
        session, repo = await self._chat(session_id)
        main, *linked = await checkouts(repo.path)
        users = await self._store.worktree_users({session.id})
        lines = [f"{PROJECT}: the project folder {main.path}, on {main.branch}"]
        for checkout in linked:
            lines.append(await self._described(repo, session, checkout, users))
        return "\n".join(lines)

    async def _described(
        self, repo: RepoConfig, session: Session, checkout: Checkout, users: list[Path]
    ) -> str:
        path = checkout.path
        here = session.worktree_path is not None and await _same(path, session.worktree_path)
        if here:
            whose = "this chat works here"
        elif await asyncio.to_thread(among, path, users):
            whose = "another open chat works here"
        else:
            whose = "no open chat works here"
        owner = "" if await asyncio.to_thread(self._worktrees.owns, repo, path) else ", not Nest's"
        return f"{path.name}: {path}, on {checkout.branch}, {whose}{owner}"

    async def remove(self, session_id: str, name: str | None) -> str:
        """Record removing the named worktree, else the chat's current one."""
        session, repo = await self._chat(session_id)
        if name is not None:
            path = (await self._found(repo, name)).path
        elif session.worktree_path is not None:
            path = session.worktree_path
        else:
            msg = "This chat works in the project folder. Name the worktree to remove."
            raise MoveRefusedError(msg)
        await self._require_removable(repo, session, path)
        current = session.worktree_path is not None and await _same(path, session.worktree_path)
        if current:
            self._require_quiet(session)
        await self._record(session, WorktreeChange(action="remove", path=path))
        after = f"the next message continues here, in {repo.path}" if current else "nothing else"
        return (
            f"Recorded. When this turn ends Nest removes the worktree {path}; its branch stays"
            f" and {after} changes. Finish your reply now; it is not gone yet."
        )

    async def new(self, session_id: str, branch: str | None, base: str | None) -> str:
        """Record a new worktree from branch `base`, else the project's default branch."""
        session, repo = await self._chat(session_id)
        self._require_quiet(session)
        if branch is not None:
            await self._worktrees.check_new_branch(repo, branch)
        commit = None if base is None else await self._worktrees.branch_commit(repo, base)
        await self._record(session, WorktreeChange(action="new", branch=branch, base=commit))
        return (
            "Recorded. When this turn ends Nest makes the worktree and the next message"
            " continues in it, with this conversation. Finish your reply now."
        )

    async def back(self, session_id: str, name: str) -> str:
        """Record going back to a worktree of the project, or to the project folder."""
        session, repo = await self._chat(session_id)
        self._require_quiet(session)
        path = None if name == PROJECT else (await self._found(repo, name)).path
        if path is not None:
            await self._joined(repo, path)
        await self._record(session, WorktreeChange(action="back", path=path))
        return (
            f"Recorded. When this turn ends this chat moves to {path or repo.path} and the next"
            " message continues there, with this conversation. Finish your reply now."
        )

    async def cancel_recorded(self, session_id: str) -> str:
        """Forget what this turn recorded."""
        await self._store.update(session_id, pending_worktree=None)
        return "Nothing will change when this turn ends."

    async def pending(self, session_id: str) -> bool:
        return (await self._store.get(session_id)).pending_worktree is not None

    async def apply(self, live: LiveSession) -> None:
        """Apply what the turn recorded, in order. The git work of each change finishes
        even when the turn is stopped meanwhile; a new worktree's setup can be cut off.
        """
        session_id = live.session_id
        session = await self._store.get(session_id)
        pending = session.pending_worktree
        if pending is None:
            return
        changes = list(pending.changes)
        try:
            repo = self._repos.get(session.repo)
            while changes:
                change, *changes = changes
                worktree = await uninterrupted(
                    asyncio.ensure_future(self._applied(live, repo, change, changes))
                )
                if worktree is not None:
                    await self._set_up(session_id, repo, worktree)
        except Exception as error:
            logger.warning("a worktree change of %s failed (%s)", session_id, _reason(error))
            await self._refused(session_id, _reason(error))

    async def cancel(self, session_id: str) -> None:
        """The turn did not end normally: what it recorded does not happen."""
        if await self.pending(session_id):
            await self._refused(session_id, _STOPPED)

    async def drop(self, session_id: str) -> None:
        """The chat closes or is archived: nothing it recorded happens, nobody hears."""
        if await self.pending(session_id):
            await self._store.update(session_id, pending_worktree=None)

    async def take_note(self, session_id: str) -> str | None:
        """What the agent should hear with its next message, once."""
        session = await self._store.get(session_id)
        note = session.worktree_note
        if note is not None:
            await self._store.update(session_id, worktree_note=None)
        return note

    async def worktree_removed(self, repo: str, path: Path) -> None:
        """Chats that left the worktree show it deleted."""
        for session_id in await self._store.worktree_removed(repo, path):
            session = await self._store.get(session_id)
            await announce_changes(self._bus, session, {"earlier_worktrees"})

    async def _chat(self, session_id: str) -> tuple[Session, RepoConfig]:
        session = await self._store.get(session_id)
        require_open(session)
        return session, await self._repos.git_repo(session.repo)

    async def _found(self, repo: RepoConfig, name: str) -> Checkout:
        """The linked worktree by folder name, path or branch."""
        _, *linked = await checkouts(repo.path)
        for checkout in linked:
            if name in (checkout.path.name, str(checkout.path), checkout.branch):
                return checkout
        if await asyncio.to_thread(Path(name).is_dir):
            target = Path(name)
            for checkout in linked:
                if await _same(checkout.path, target):
                    return checkout
        msg = f"{repo.name} has no worktree {name!r}. The list action shows them."
        raise MoveRefusedError(msg)

    async def _require_removable(self, repo: RepoConfig, session: Session, path: Path) -> None:
        if not await asyncio.to_thread(self._worktrees.owns, repo, path):
            msg = f"Nest did not make the worktree {path}, so it stays."
            raise MoveRefusedError(msg)
        users = await self._store.worktree_users({session.id})
        if await asyncio.to_thread(among, path, users):
            msg = f"Another open chat works in the worktree {path}, so it stays."
            raise MoveRefusedError(msg)

    def _require_quiet(self, session: Session) -> None:
        if self._background(session.id):
            msg = (
                "The agent's background tasks are running and end when this chat moves."
                " Wait for them, then try again."
            )
            raise MoveRefusedError(msg)

    async def _joined(self, repo: RepoConfig, path: Path) -> Worktree:
        bases = await self._store.worktree_bases(repo.name)
        return await join_worktree(repo, path, bases, self._worktrees)

    async def _record(self, session: Session, change: WorktreeChange) -> None:
        earlier = session.pending_worktree.changes if session.pending_worktree else []
        pending = PendingWorktree(changes=[*earlier, change])
        await self._store.update(session.id, pending_worktree=pending)

    async def _applied(
        self,
        live: LiveSession,
        repo: RepoConfig,
        change: WorktreeChange,
        rest: list[WorktreeChange],
    ) -> Worktree | None:
        """One change; the new worktree left to set up, if it made one."""
        session = await self._store.get(live.session_id)
        made = None
        match change.action:
            case "remove":
                await self._remove(live, repo, session, change)
            case "new":
                made = await self._new(live, repo, session, change)
            case "back":
                await self._back(live, repo, session, change)
        left = PendingWorktree(changes=rest) if rest else None
        await self._store.update(live.session_id, pending_worktree=left)
        return made

    async def _remove(
        self, live: LiveSession, repo: RepoConfig, session: Session, change: WorktreeChange
    ) -> None:
        path = change.path
        assert path is not None  # noqa: S101 (recorded with the tool's call)
        await self._require_removable(repo, session, path)
        current = session.worktree_path is not None and await _same(path, session.worktree_path)
        if current:
            await self._end_run(live, session)
        worktree = Worktree(path, session.branch or "", session.base_ref or "")
        try:
            removed = await self._remove_worktree(repo, session, worktree)
        except GitError:
            # Half done, the folder may be gone: then the chat cannot stay there.
            if await asyncio.to_thread(path.is_dir):
                raise
            removed = True
        if not removed:
            msg = f"The worktree {path} stayed: another open chat works in it."
            raise MoveRefusedError(msg)
        if current:
            head = await self._worktrees.head(repo)
            await self._moved(session, repo, Place("in_place", head), "deleted")
        await self._say(session.id, f"Worktree {path.name} removed. Its branch stays.")

    async def _new(
        self, live: LiveSession, repo: RepoConfig, session: Session, change: WorktreeChange
    ) -> Worktree:
        await self._end_run(live, session)
        taken = {entry.path.name for entry in session.earlier_worktrees}
        if session.worktree_path is not None:
            taken.add(session.worktree_path.name)
        worktree = await self._worktrees.create(
            repo,
            session.id,
            session.title,
            change.branch,
            change.base,
            self._worktrees.free_folder(repo, session.id, taken),
        )
        place = Place("worktree", worktree.base_ref, worktree.branch, worktree)
        links = self._worktrees.link(repo, worktree.path)
        await self._moved(session, repo, place, "kept", links)
        await self._say(session.id, f"This chat moved to a new worktree on {worktree.branch}.")
        return worktree

    async def _back(
        self, live: LiveSession, repo: RepoConfig, session: Session, change: WorktreeChange
    ) -> None:
        path = change.path
        if path is None:
            await self._end_run(live, session)
            head = await self._worktrees.head(repo)
            await self._moved(session, repo, Place("in_place", head), "kept")
            await self._say(session.id, "This chat moved to the project folder.")
            return
        worktree = await self._joined(repo, path)
        await self._end_run(live, session)
        place = Place("worktree", worktree.base_ref, worktree.branch, worktree)
        await self._moved(session, repo, place, "kept")
        await self._say(session.id, f"This chat moved back to {worktree.branch}.")

    async def _end_run(self, live: LiveSession, session: Session) -> None:
        """The run works in the old folder, and so do the pixies it called."""
        self._require_quiet(session)
        if self.bridge is not None:
            await isolated("the called pixies", session.id, self.bridge.released(session.id))
        await live.close_run()

    async def _moved(
        self,
        session: Session,
        repo: RepoConfig,
        place: Place,
        left: EarlierState,
        links: LinkResult | None = None,
    ) -> None:
        """Record where the chat works now and what became of the worktree it left, then
        announce it. Clients apply `session.updated` last, so it settles what they show.
        """
        now = self._clock.now()
        target = repo.path if place.worktree is None else place.worktree.path
        changes: dict[str, object] = {
            **_LEFT_BEHIND,
            "mode": place.mode,
            "cwd": target,
            "worktree_path": None if place.worktree is None else target,
            "branch": place.branch,
            "base_ref": place.base_ref,
            "moved_at": now,
            "earlier_worktrees": await self._earlier(session, target, left),
        }
        session = await self._store.update(session.id, **changes)
        await self._bus.publish(
            types.SESSION_WORKSPACE,
            {
                **workspace_payload(target, place.branch, place.base_ref, links or LinkResult()),
                "mode": place.mode,
                "worktree_path": None if place.worktree is None else str(target),
                "earlier_worktrees": _entries(session),
            },
            session.id,
        )
        await announce_changes(self._bus, session, set(changes))
        # Also with its next message: not every engine reads the prompt when it resumes.
        note = place_note(session)
        await self._store.update(session.id, worktree_note=note and _as_note(note))
        await self._store.called_followed(session.id, target)
        # Reviews, merges and comments that waited were about the place it left.
        await self._approvals.expire(session.id, tuple(ApprovalKind), "the chat moved")
        await isolated("the move hooks", session.id, self._hooks.moved(session))

    async def _earlier(
        self, session: Session, target: Path, left: EarlierState
    ) -> list[dict[str, JsonValue]]:
        """The chat's earlier worktrees once it works at `target`, which leaves the list."""
        entries = [
            entry for entry in session.earlier_worktrees if not await _same(entry.path, target)
        ]
        if session.worktree_path is not None and not await _same(session.worktree_path, target):
            entries.append(
                EarlierWorktree(
                    path=session.worktree_path,
                    branch=session.branch,
                    base_ref=session.base_ref,
                    started_at=session.moved_at or session.created_at,
                    ended_at=self._clock.now(),
                    state=left,
                )
            )
        return [entry.model_dump(mode="json") for entry in entries]

    async def _set_up(self, session_id: str, repo: RepoConfig, worktree: Worktree) -> None:
        """A failed setup leaves the chat in the new worktree, as a failure the user sees."""
        setup = await run_setup(session_id, repo, worktree, self._worktrees, self._bus)
        if not setup.ok:
            note = f"The setup command {setup.command!r} of this new worktree failed."
            await self._store.update(session_id, worktree_note=_as_note(note))

    async def _refused(self, session_id: str, reason: str) -> None:
        """What was recorded and not done goes, and both the chat and the agent hear why."""
        await self._store.update(
            session_id,
            pending_worktree=None,
            worktree_note=_as_note(f"The worktree change you asked for did not happen: {reason}."),
        )
        await self._say(session_id, f"The worktree change did not happen: {reason}", FAILED)

    async def _say(self, session_id: str, text: str, kind: str = CHANGED) -> None:
        await self._bus.publish(types.SESSION_NOTICE, {"kind": kind, "text": text}, session_id)


def place_note(session: Session) -> str | None:
    """Where a chat that moved works now, for its agent: earlier messages name other
    folders. None for one that never moved.
    """
    if session.moved_at is None:
        return None
    where = (
        "the project folder, as a normal chat"
        if session.worktree_path is None
        else f"a worktree on branch {session.branch}"
    )
    return (
        f"This chat moved: it works in {session.cwd} now, {where}. Folders named earlier in"
        " this conversation may be gone, so use this one."
    )


def _as_note(text: str) -> str:
    return f"[Nest: {text}]"


def _reason(error: Exception) -> str:
    if isinstance(error, CommandError):
        return error.stderr.strip() or str(error)
    return str(error) if isinstance(error, NestError) else f"{type(error).__name__}: {error}"


def _entries(session: Session) -> list[JsonValue]:
    return [entry.model_dump(mode="json") for entry in session.earlier_worktrees]


async def _same(one: Path, other: Path) -> bool:
    return await asyncio.to_thread(among, one, (other,))
