"""Session lifecycle commands: create, send, interrupt, update, close, purge.

Each session has at most one background task (setup plus the first turn, or a later turn),
so turns are serialized: a message sent while one runs is queued and starts the next turn
once this one ends (D032).
"""

import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from datetime import timedelta
from pathlib import Path

from harness.approvals.models import BLOCKING, ApprovalKind
from harness.approvals.queue import ApprovalQueue
from harness.attachments.store import Attachment, AttachmentStore
from harness.claude_sessions.errors import ChatOpenElsewhereError
from harness.claude_sessions.live import LiveChats
from harness.clock import Clock
from harness.config.models import AgentDefaults, Effort, PermissionMode, RepoConfig, SessionMode
from harness.engine.service import effort_problem
from harness.errors import InvalidInputError
from harness.events import types
from harness.events.bus import EventBus
from harness.gitops.remotes import REMOTE
from harness.providers.base import AgentProvider, ApprovalHandler, ModelOption
from harness.repos.service import RepoNotFoundError, RepoService, require_folder
from harness.sessions.errors import DirtyCheckoutError, NoTurnInProgressError, NoWorkspaceError
from harness.sessions.extras import RunExtrasSource
from harness.sessions.files import FileIndex
from harness.sessions.git_audit import with_own_changes
from harness.sessions.hooks import SessionHooks
from harness.sessions.live import LiveSession
from harness.sessions.models import (
    ChatImport,
    CreateSession,
    NewSession,
    QueuedMessage,
    SendResult,
    Session,
    SessionState,
    UpdateSession,
    pixie_repo,
)
from harness.sessions.prompts import SessionPrompts
from harness.sessions.queue import MessageQueue
from harness.sessions.rules import (
    require_cwd,
    require_open,
    require_workspace,
    session_changes,
    worktree_of,
)
from harness.sessions.states import StateWriter
from harness.sessions.store import SessionStore
from harness.sessions.titles import short_title
from harness.sessions.turns import TurnRunner
from harness.worktrees.manager import WorktreeManager

# The engine's entry for a model (None is Claude Code's default), or None when unknown.
type ModelLookup = Callable[[str | None], Awaitable[ModelOption | None]]


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
        defaults: Callable[[], AgentDefaults],
        idle_close: timedelta,
        clock: Clock,
        live_chats: LiveChats,
        queue: MessageQueue,
        files: FileIndex | None = None,
        models: ModelLookup | None = None,
        extras: RunExtrasSource | None = None,
    ) -> None:
        """`defaults` is read for each new session, so edits apply at once; `models`
        checks a new session's effort against its model (D038).
        """
        self._models = models
        self._queue = queue
        self._files = files or FileIndex(clock)
        self._clock = clock
        self._live_chats = live_chats
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
            repos=repos,
            attachments=attachments,
            provider=provider,
            handler_for=self._handler_for,
            on_mode=self._engine_mode,
            idle_close=idle_close,
            queue=queue,
            clock=clock,
            extras=extras,
        )
        self._live: dict[str, LiveSession] = {}

    async def list_sessions(self, repo: str | None = None, archived: bool = False) -> list[Session]:
        return await self._store.list_sessions(repo, archived)

    async def get(self, session_id: str) -> Session:
        return await self._store.get(session_id)

    async def find_by_provider_session(self, provider_session_id: str) -> Session | None:
        return await self._store.find_by_provider_session(provider_session_id)

    def busy(self, session_id: str) -> bool:
        """Whether a turn or the session's start is in progress in this process."""
        live = self._live.get(session_id)
        return live is not None and live.busy

    def has_run(self, session_id: str) -> bool:
        """Whether this process runs (or is starting, or still closing) the session's agent."""
        live = self._live.get(session_id)
        return live is not None and (
            live.run is not None or live.busy or not live.run_closed.is_set()
        )

    async def create(self, request: CreateSession) -> Session:
        try:
            repo = await self._repos.current(request.repo)
        except RepoNotFoundError as error:
            raise InvalidInputError(str(error)) from error
        require_folder(repo)
        defaults = self._defaults()
        model = request.model or defaults.model
        effort = await self._effort(model, request.effort, defaults.effort)
        # A plain folder has no worktrees or branches: its chats always work in place (D041).
        mode = (
            (request.mode or _repo_mode(repo) or defaults.default_mode) if repo.git else "in_place"
        )
        if mode == "in_place" and repo.git and not request.allow_dirty:
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
                model=model,
                effort=effort,
                permission_mode=request.permission_mode or defaults.permission_mode,
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

    async def create_pixie_chat(
        self,
        *,
        pixie_id: str,
        cwd: Path,
        prompt: str,
        title: str,
        model: str | None,
        effort: Effort | None,
        permission_mode: PermissionMode,
        attachment_ids: list[str],
    ) -> Session:
        """A pixie's chat: in place in its workdir, with no project, review or git (D057)."""
        attachments = await self._attachments.for_session(attachment_ids, None)
        session = await self._store.create(
            NewSession(
                repo=pixie_repo(pixie_id),
                title=title,
                prompt=prompt,
                mode="in_place",
                cwd=cwd,
                model=model,
                effort=await self._effort(model, effort, None),
                permission_mode=permission_mode,
                provider=self._provider.name,
                pixie_id=pixie_id,
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
            lambda: self._turns.guard(live, self._turns.start(live, session, None, attachments))
        )
        return session

    def refresh_run(self, session_id: str) -> None:
        """What a pixie chat's run is opened with changed: its next turn opens a fresh run.
        The run in use is left alone, so a turn in progress finishes as it began (D057).
        """
        live = self._live.get(session_id)
        if live is not None:
            live.rotate = True

    async def adopt(self, chat: ChatImport) -> Session:
        """Continue a Claude Code chat as an idle in-place session in the chat's own folder.

        Its history is copied into the session's events; the next message resumes the
        chat through the engine. Harness never removes that folder (no worktree is set).
        """
        try:
            repo = self._repos.get(chat.repo)
        except RepoNotFoundError as error:
            raise InvalidInputError(str(error)) from error
        require_folder(repo)
        if not await asyncio.to_thread(chat.cwd.is_dir):
            msg = f"the folder of this chat no longer exists: {chat.cwd}"
            raise NoWorkspaceError(msg)
        defaults = self._defaults()
        created = await self._store.create(
            NewSession(
                repo=repo.name,
                title=chat.title,
                prompt=chat.prompt,
                mode="in_place",
                cwd=chat.cwd,
                model=defaults.model,
                effort=defaults.effort,
                permission_mode=defaults.permission_mode,
                provider=self._provider.name,
                base_ref=await self._worktrees.head_at(chat.cwd),
            )
        )
        session = await self._store.update(
            created.id,
            state=SessionState.IDLE,
            provider_session_id=chat.provider_session_id,
        )
        await self._bus.publish(
            types.SESSION_CREATED, {"session": session.model_dump(mode="json")}, session.id
        )
        await self._bus.publish(
            types.SESSION_STATE, {"state": session.state, "error": None}, session.id
        )
        for event_type, payload in chat.history:
            await self._bus.publish(event_type, payload, session.id)
        return session

    async def send(
        self, session_id: str, text: str, attachment_ids: list[str], interrupt: bool = False
    ) -> SendResult:
        """Start a turn, or queue the message while one runs. Without a live run, the agent
        is resumed from its last session. With `interrupt`, a running turn is stopped and
        the message starts as soon as it ends, ahead of the rest of the queue.

        Refused while Claude Code has the chat open elsewhere, since both would write it.
        A pending review of the session's work is superseded: the work is changing. While
        the daemon publishes the work, the message is queued and starts once that is done.
        """
        session = await self._store.get(session_id)
        require_open(session)
        await self._require_not_open_elsewhere(session)
        live = self._live.setdefault(session_id, LiveSession(session_id))
        attachments = await self._attachments.for_session(attachment_ids, session_id)
        await live.settled.wait()
        # Nothing is awaited from here until the turn starts, so of two messages sent at
        # once the second is queued (D032).
        if live.busy or live.publishing:
            return await self._enqueue(live, session, text, attachments, interrupt)
        require_cwd(session)
        live.start(lambda: self._turns.guard(live, self._send_turn(live, text, attachments)))
        return SendResult(**session.model_dump())

    async def _enqueue(
        self,
        live: LiveSession,
        session: Session,
        text: str,
        attachments: list[Attachment],
        interrupt: bool,
    ) -> SendResult:
        queued = await self._queue.add(session.id, text, attachments, urgent=interrupt)
        if interrupt and live.busy:
            live.resume_queue = True
            await self._approvals.expire(session.id, BLOCKING, "interrupted by the user")
            await live.interrupt()
        return SendResult(**session.model_dump(), queued_message=queued)

    async def _send_turn(self, live: LiveSession, text: str, attachments: list[Attachment]) -> None:
        await self._approvals.supersede(live.session_id, ApprovalKind.REVIEW)
        await self._turns.submit(live, text, attachments)

    async def queued(self, session_id: str) -> list[QueuedMessage]:
        await self._store.get(session_id)
        return await self._queue.messages(session_id)

    async def cancel_queued(self, session_id: str, message_id: str) -> None:
        await self._store.get(session_id)
        await self._queue.cancel(session_id, message_id)

    async def files(self, session_id: str, query: str) -> list[str]:
        """Files in the session's working directory matching `query`, for @ mentions."""
        session = await self._store.get(session_id)
        cwd = require_workspace(session)
        if session.pixie_id is not None:
            return []  # a pixie's workdir is not a repository
        if not await self._repos.has_git(session.repo):
            return []  # the listing comes from git (D041)
        return await self._files.search(cwd, query)

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
        if (request.model, request.permission_mode, request.effort) != (None, None, None):
            require_open(session)
        changes = session_changes(session, request, self._clock.now())
        if not changes:
            return session
        if changes.get("archived_at") is not None:
            await self._release(session_id, "the session was archived")
        session = await self._save_changes(session_id, changes)
        live = self._live.get(session_id)
        if live is not None and {"model", "permission_mode"} & changes.keys():
            # Read back from the store, so of two quick changes the last one wins (D048).
            await self._turns.apply_controls(live)
        return session

    async def close(self, session_id: str, remove_worktree: bool) -> Session:
        require_open(await self._store.get(session_id))
        session = await self._stop(session_id, "the session was closed")
        await self._queue.clear(session_id)
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

    @asynccontextmanager
    async def publishing(self, session_id: str) -> AsyncGenerator[None]:
        """Hold new turns off while the daemon commits, pushes or merges the session's work
        (BUG-14): a message sent meanwhile is queued and starts afterwards, and a turn the
        agent starts on its own waits.
        """
        await self._store.get(session_id)
        live = self._live.setdefault(session_id, LiveSession(session_id))
        live.published.clear()
        try:
            yield
        finally:
            live.published.set()
            if self._live.get(session_id) is live:
                await self._turns.deliver_queued(live)

    async def audit_refs(self, session_id: str) -> None:
        """Check HEAD and the local branches right before the daemon publishes: a
        background command of the agent may have changed them after the last turn's audit
        (D013 layer 4). A change sets `git_violation`. Other refs, such as those a fetch
        moves, are left to the next turn-end audit. Without an audit in this process
        (after a restart) there is nothing to compare with, and the refs as they are
        become the baseline.
        """
        live = self._live.setdefault(session_id, LiveSession(session_id))
        await self._turns.audit(live, publishing=True)

    async def refresh_refs(self, session_id: str) -> None:
        """The daemon changed the session's refs itself (commit, push); the next turn's
        ref audit (D013 layer 4) must not report that as the agent's doing, but still
        reports any other change.
        """
        live = self._live.setdefault(session_id, LiveSession(session_id))
        cwd = require_cwd(await self._store.get(session_id))
        live.baseline = await with_own_changes(cwd, live.baseline, REMOTE)

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

    async def _require_not_open_elsewhere(self, session: Session) -> None:
        if session.provider_session_id is None:
            return
        elsewhere = await asyncio.to_thread(
            self._live_chats.open_elsewhere,
            session.provider_session_id,
            self.has_run(session.id),
        )
        if elsewhere:
            raise ChatOpenElsewhereError

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
            duration = live.turn_ms(self._clock.now())
            await self._states.set(
                live.session_id, SessionState.INTERRUPTED, turn={"duration_ms": duration}
            )

    async def _save_changes(self, session_id: str, changes: dict[str, object]) -> Session:
        session = await self._store.update(session_id, **changes)
        await self._bus.publish(
            types.SESSION_UPDATED,
            {
                "changes": session.model_dump(mode="json", include=set(changes)),
                "session": session.model_dump(mode="json"),
            },
            session_id,
        )
        return session

    async def _effort(
        self, model: str | None, chosen: Effort | None, default: Effort | None
    ) -> Effort | None:
        """The chosen effort, refused (422) when the model does not take it; the default
        effort only when the model takes it. Unchecked while the model list is unknown.
        """
        option = None if self._models is None else await self._models(model)
        if option is None:
            return chosen or default
        if chosen is not None:
            problem = effort_problem(option, chosen)
            if problem is not None:
                raise InvalidInputError(problem)
            return chosen
        return default if effort_problem(option, default) is None else None

    def _handler_for(self, live: LiveSession) -> ApprovalHandler:
        async def on_mode(_session_id: str, mode: PermissionMode) -> None:
            await self._engine_mode(live, mode)

        return SessionPrompts(
            live.session_id, self._approvals, self._store, self._on_waiting, on_mode
        )

    async def _engine_mode(self, live: LiveSession, mode: PermissionMode) -> None:
        """The agent's engine switched mode itself (an approved plan, or a switch it
        reported); the run has it now, and the session records and announces it.
        """
        live.run_mode = mode
        if (await self._store.get(live.session_id)).permission_mode != mode:
            await self._save_changes(live.session_id, {"permission_mode": mode})

    async def _on_waiting(self, session_id: str, waiting: bool) -> None:
        live = self._live.get(session_id)
        if live is None:
            return  # closing or shutting down; that sets the final state
        async with live.prompts:
            current = (await self._store.get(session_id)).state
            target = SessionState.WAITING if waiting else SessionState.RUNNING
            if current in (SessionState.RUNNING, SessionState.WAITING) and current is not target:
                await self._states.set(session_id, target)


def _repo_mode(repo: RepoConfig) -> SessionMode | None:
    """The repo's own choice, when its config sets `[worktree] default`."""
    if repo.worktree.default is None:
        return None
    return "worktree" if repo.worktree.default else "in_place"
