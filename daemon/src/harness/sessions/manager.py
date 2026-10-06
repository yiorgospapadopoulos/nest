"""Session lifecycle commands: create, send, interrupt, update, close, purge.

Each session has at most one background task (setup plus the first turn, or a later turn),
so turns are serialized: a message sent while one runs is rejected, not queued.
"""

import asyncio
from contextlib import suppress
from datetime import timedelta

from harness.approvals.models import BLOCKING, ApprovalKind
from harness.approvals.queue import ApprovalQueue
from harness.attachments.store import AttachmentStore
from harness.clock import Clock
from harness.config.models import AgentDefaults
from harness.errors import InvalidInputError
from harness.events import types
from harness.events.bus import EventBus
from harness.providers.base import AgentProvider, ApprovalHandler
from harness.repos.service import RepoNotFoundError, RepoService
from harness.sessions.errors import DirtyCheckoutError, NoTurnInProgressError
from harness.sessions.git_audit import snapshot_refs
from harness.sessions.hooks import SessionHooks
from harness.sessions.live import LiveSession
from harness.sessions.models import (
    CreateSession,
    NewSession,
    Session,
    SessionState,
    UpdateSession,
)
from harness.sessions.prompts import SessionPrompts
from harness.sessions.rules import require_cwd, require_open, session_changes, worktree_of
from harness.sessions.states import StateWriter
from harness.sessions.store import SessionStore
from harness.sessions.titles import short_title
from harness.sessions.turns import TurnRunner
from harness.worktrees.manager import WorktreeManager


class SessionManager:
    def __init__(
        self,
        *,
        store: SessionStore,
        bus: EventBus,
        repos: RepoService,
        worktrees: WorktreeManager,
        attachments: AttachmentStore,
        provider: AgentProvider,
        approvals: ApprovalQueue,
        hooks: SessionHooks,
        defaults: AgentDefaults,
        idle_close: timedelta,
        clock: Clock,
    ) -> None:
        self._clock = clock
        self._store = store
        self._bus = bus
        self._repos = repos
        self._worktrees = worktrees
        self._attachments = attachments
        self._provider = provider
        self._approvals = approvals
        self._defaults = defaults
        self._states = StateWriter(store, bus, hooks)
        self._turns = TurnRunner(
            store=store,
            bus=bus,
            states=self._states,
            hooks=hooks,
            worktrees=worktrees,
            attachments=attachments,
            provider=provider,
            handler_for=self._handler_for,
            idle_close=idle_close,
        )
        self._live: dict[str, LiveSession] = {}

    async def list_sessions(self, repo: str | None = None, archived: bool = False) -> list[Session]:
        return await self._store.list_sessions(repo, archived)

    async def get(self, session_id: str) -> Session:
        return await self._store.get(session_id)

    def busy(self, session_id: str) -> bool:
        """Whether a turn or the session's start is in progress in this process."""
        live = self._live.get(session_id)
        return live is not None and live.busy

    def has_run(self, session_id: str) -> bool:
        """Whether this process runs (or is starting) the session's agent."""
        live = self._live.get(session_id)
        return live is not None and (live.run is not None or live.busy)

    async def create(self, request: CreateSession) -> Session:
        try:
            repo = self._repos.get(request.repo)
        except RepoNotFoundError as error:
            raise InvalidInputError(str(error)) from error
        mode = request.mode or ("worktree" if repo.worktree.default else "in_place")
        if mode == "in_place" and not request.allow_dirty:
            dirty = await self._worktrees.dirty_files(repo)
            if dirty:
                raise DirtyCheckoutError(dirty)
        attachments = await self._attachments.for_session(request.attachment_ids, None)
        session = await self._store.create(
            NewSession(
                repo=repo.name,
                title=request.title or short_title(request.prompt),
                prompt=request.prompt,
                mode=mode,
                cwd=repo.path if mode == "in_place" else None,
                model=request.model or self._defaults.model,
                effort=request.effort or self._defaults.effort,
                permission_mode=request.permission_mode or self._defaults.permission_mode,
                provider=self._provider.name,
                # Worktree sessions get their base when the worktree is created.
                base_ref=await self._worktrees.head(repo) if mode == "in_place" else None,
            )
        )
        await self._bus.publish(
            types.SESSION_CREATED, {"session": session.model_dump(mode="json")}, session.id
        )
        await self._bus.publish(
            types.SESSION_STATE, {"state": session.state, "error": None}, session.id
        )
        live = self._live.setdefault(session.id, LiveSession(session.id))
        live.start(
            lambda: self._turns.guard(live, self._turns.start(live, session, repo, attachments))
        )
        return session

    async def send(self, session_id: str, text: str, attachment_ids: list[str]) -> Session:
        """Start a turn. Without a live run, the agent is resumed from its last session.

        A pending review of the session's work is superseded: the work is changing.
        """
        session = await self._store.get(session_id)
        require_open(session)
        live = self._live.setdefault(session_id, LiveSession(session_id))
        live.require_idle()
        require_cwd(session)
        attachments = await self._attachments.for_session(attachment_ids, session_id)
        await self._approvals.supersede(session_id, ApprovalKind.REVIEW)
        live.start(lambda: self._turns.guard(live, self._turns.submit(live, text, attachments)))
        return session

    async def interrupt(self, session_id: str) -> None:
        await self._store.get(session_id)
        await self._approvals.expire(session_id, BLOCKING, "interrupted by the user")
        live = self._live.get(session_id)
        if live is None or not await live.interrupt():
            msg = f"session {session_id!r} has no turn in progress"
            raise NoTurnInProgressError(msg)

    async def update(self, session_id: str, request: UpdateSession) -> Session:
        """Rename, pin or archive; persist new controls and apply them to the live run.

        Archiving closes the agent run but keeps the worktree; a new message resumes it.
        """
        session = await self._store.get(session_id)
        if request.model is not None or request.permission_mode is not None:
            require_open(session)
        changes = session_changes(session, request, self._clock.now())
        if not changes:
            return session
        if changes.get("archived_at") is not None:
            await self._release(session_id, "the session was archived")
        session = await self._store.update(session_id, **changes)
        await self._bus.publish(
            types.SESSION_UPDATED,
            {
                "changes": session.model_dump(mode="json", include=set(changes)),
                "session": session.model_dump(mode="json"),
            },
            session_id,
        )
        live = self._live.get(session_id)
        run = live.run if live is not None else None
        if run is not None:
            if "model" in changes:
                await run.set_model(session.model)
            if "permission_mode" in changes:
                await run.set_permission_mode(session.permission_mode)
        return session

    async def close(self, session_id: str, remove_worktree: bool) -> Session:
        require_open(await self._store.get(session_id))
        session = await self._stop(session_id, "the session was closed")
        worktree = worktree_of(session)
        if remove_worktree and worktree is not None:
            await self._worktrees.remove(
                self._repos.get(session.repo), worktree, delete_branch=True
            )
        return await self._states.set(session_id, SessionState.CLOSED)

    async def purge(self, session_id: str) -> None:
        """Delete the session for good: its run, worktree and branch, and all it stored."""
        await self._store.get(session_id)
        session = await self._stop(session_id, "the session was deleted")
        worktree = worktree_of(session)
        if worktree is not None:
            # Without the repo's config git cannot clean up; the rest is deleted anyway.
            with suppress(RepoNotFoundError):
                repo = self._repos.get(session.repo)
                await self._worktrees.remove(repo, worktree, delete_branch=True)
        await self._attachments.delete_files(session_id)
        await self._store.delete(session_id)
        # Not a session event: the session's events are gone with it.
        await self._bus.publish(types.SESSION_DELETED, {"session_id": session_id})

    async def refresh_refs(self, session_id: str) -> None:
        """The daemon changed the session's refs itself (commit, push); the next turn's
        ref audit (D013 layer 4) must not report that as the agent's doing.
        """
        live = self._live.get(session_id)
        if live is not None:
            live.baseline = await snapshot_refs(require_cwd(await self._store.get(session_id)))

    async def recover(self) -> None:
        """On startup, turns cut off by the previous process can only be resumed."""
        for session_id in await self._store.interrupt_in_flight():
            await self._bus.publish(
                types.SESSION_STATE, {"state": SessionState.INTERRUPTED, "error": None}, session_id
            )

    async def shutdown(self) -> None:
        """Stop every agent. A turn cut off here is interrupted, as after a hard kill."""
        lives = list(self._live.values())
        self._live.clear()
        await asyncio.gather(*(self._shut_down(live, "the daemon stopped") for live in lives))

    async def _stop(self, session_id: str, reason: str) -> Session:
        """Expire everything pending and stop the agent; returns the session as it is now."""
        await self._approvals.expire(session_id, tuple(ApprovalKind), reason)
        live = self._live.pop(session_id, None)
        if live is not None:
            await live.stop()
        # Read again: setup may have created the worktree while the session was starting.
        return await self._store.get(session_id)

    async def _release(self, session_id: str, reason: str) -> None:
        live = self._live.pop(session_id, None)
        if live is not None:
            await self._shut_down(live, reason)

    async def _shut_down(self, live: LiveSession, reason: str) -> None:
        await self._approvals.expire(live.session_id, BLOCKING, reason)
        await live.stop()
        if live.turn_active:
            live.turn_active = False
            await self._states.set(live.session_id, SessionState.INTERRUPTED)

    def _handler_for(self, session_id: str) -> ApprovalHandler:
        return SessionPrompts(session_id, self._approvals, self._store, self._on_waiting)

    async def _on_waiting(self, session_id: str, waiting: bool) -> None:
        if session_id not in self._live:
            return  # closing or shutting down; that sets the final state
        current = (await self._store.get(session_id)).state
        target = SessionState.WAITING if waiting else SessionState.RUNNING
        if current in (SessionState.RUNNING, SessionState.WAITING) and current is not target:
            await self._states.set(session_id, target)
