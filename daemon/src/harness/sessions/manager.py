"""Session lifecycle commands: create, send, interrupt, update, close, purge.

Each session has at most one background task (setup plus the first turn, or a later turn),
so turns are serialized: a message sent while one runs is queued and starts the next turn
once this one ends (D032).
"""

import asyncio
import logging
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
from harness.engine.service import effort_problem, mode_problem
from harness.errors import InvalidInputError
from harness.events import types
from harness.events.bus import EventBus
from harness.gitops.remotes import REMOTE
from harness.providers.base import AgentProvider, ApprovalHandler, ModelOption, RewindResult
from harness.repos.service import RepoNotFoundError, RepoService, require_folder
from harness.sessions.errors import (
    CannotRewindError,
    DirtyCheckoutError,
    NoTurnInProgressError,
    NoWorkspaceError,
    PixieChatError,
    SessionBusyError,
)
from harness.sessions.extras import RunExtrasSource
from harness.sessions.files import FileIndex
from harness.sessions.git_audit import with_own_changes
from harness.sessions.hooks import SessionHooks
from harness.sessions.live import BYPASS, LiveSession
from harness.sessions.models import (
    USER,
    ChatImport,
    CreateSession,
    NewSession,
    QueuedMessage,
    Sender,
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
from harness.sessions.subagents import ChatAgentsSource
from harness.sessions.titles import short_title
from harness.sessions.turns import TurnRunner
from harness.sessions.updates import save_changes, set_git_violation
from harness.worktrees.manager import WorktreeManager

# What a session following Claude Code's own mode shows until the engine reports it.
DEFAULT_MODE: PermissionMode = "default"
AUTO: PermissionMode = "auto"

NO_CHECKPOINT = (
    "harness has no file checkpoint for this message: it was sent before checkpoints were "
    "kept, in Claude Code, or as a command"
)

NO_RUN_TO_PREVIEW = (
    "Claude Code is not running for this chat, so the files to restore cannot be listed. "
    "Send a message to start it again, then try again."
)
NO_PIXIE_RESTORE = (
    "Files cannot be restored in a pixie's chat: each of its runs starts fresh, so the "
    "earlier ones' checkpoints are gone."
)

# The engine's entry for a model (None is Claude Code's default), or None when unknown.
type ModelLookup = Callable[[str | None], Awaitable[ModelOption | None]]

logger = logging.getLogger(__name__)


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
        agents: ChatAgentsSource | None = None,
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
        self._hooks = hooks
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
            agents=agents,
        )
        self._live: dict[str, LiveSession] = {}
        # Set when the daemon stops its agents: no message starts a turn after that.
        self._stopping = False

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

    async def create(
        self,
        request: CreateSession,
        *,
        started_by_pixie: str | None = None,
        pixie_batch: str | None = None,
    ) -> Session:
        """`started_by_pixie` marks a chat a pixie starts with its tools, in the batch of
        its turn; its prompt is shown as the pixie's. Such a chat needs a git repository,
        since it must work in its own worktree (B41).
        """
        try:
            repo = await self._repos.current(request.repo)
        except RepoNotFoundError as error:
            raise InvalidInputError(str(error)) from error
        require_folder(repo)
        if started_by_pixie is not None and not repo.git:
            msg = f"{repo.name} is not a git repository, so a chat cannot get its own worktree"
            raise InvalidInputError(msg)
        defaults = self._defaults()
        model = request.model or defaults.model
        effort = await self._effort(model, request.effort, defaults.effort)
        permission_mode = request.permission_mode
        await self._require_mode(model, permission_mode)
        # A default mode the model does not run in is dropped, as the effort default is.
        if permission_mode is None and not await self._mode_problem(
            model, defaults.permission_mode
        ):
            permission_mode = defaults.permission_mode
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
                permission_mode=permission_mode or DEFAULT_MODE,
                follows_claude_code_mode=permission_mode is None,
                provider=self._provider.name,
                # Worktree sessions get their base when the worktree is created.
                base_ref=await self._worktrees.head(repo) if mode == "in_place" else None,
                started_by_pixie=started_by_pixie,
                pixie_batch=pixie_batch,
            )
        )
        sender = Sender(from_pixie=started_by_pixie)
        await self._bus.publish(
            types.SESSION_CREATED, {"session": session.model_dump(mode="json")}, session.id
        )
        await self._bus.publish(
            types.SESSION_STATE, {"state": session.state, "error": None}, session.id
        )
        live = self._live.setdefault(session.id, LiveSession(session.id))
        live.start(
            lambda: self._turns.guard(
                live, self._turns.start(live, session, repo, attachments, sender)
            )
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
        sender: Sender = USER,
        habit_run_id: str | None = None,
    ) -> Session:
        """A pixie's chat: in place in its workdir, with no project, review or git (D072).
        Refused (422) when the model does not run in the pixie's mode, as for any chat.
        With `habit_run_id` it is the session of one run of the pixie's habit (B42).
        """
        await self._require_mode(model, permission_mode)
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
                habit_run_id=habit_run_id,
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
            lambda: self._turns.guard(
                live, self._turns.start(live, session, None, attachments, sender)
            )
        )
        return session

    async def set_pixie_controls(self, session_id: str, controls: dict[str, object]) -> None:
        """Save a pixie's new title, model, effort or mode on its chat as they are, null
        included (back to the default), and apply them to the live run. The pixie service
        has checked them; a new effort opens a new run next turn (D072).
        """
        session = await self._store.get(session_id)
        changes = {
            name: value for name, value in controls.items() if getattr(session, name) != value
        }
        if not changes:
            return
        await self._save_changes(session_id, changes)
        live = self._live.get(session_id)
        if live is not None and {"model", "permission_mode"} & changes.keys():
            await self._turns.apply_controls(live)

    def refresh_run(self, session_id: str) -> None:
        """What a pixie chat's run is opened with changed: its next turn opens a fresh run.
        The run in use is left alone, so a turn in progress finishes as it began (D072).
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
                permission_mode=defaults.permission_mode or DEFAULT_MODE,
                follows_claude_code_mode=defaults.permission_mode is None,
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
        await self._bus.publish_many(chat.history, session.id)
        return session

    async def send(
        self,
        session_id: str,
        text: str,
        attachment_ids: list[str],
        interrupt: bool = False,
        sender: Sender = USER,
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
        # Read again: the session may have been closed or deleted while this waited.
        session = await self._store.get(session_id)
        require_open(session)
        # Nothing is awaited from here until the turn starts, so of two messages sent at
        # once the second is queued (D032), and nothing starts on a session that is being
        # closed, archived or deleted, or while the daemon stops (BUG-53).
        if self._stopping or live.stopped:
            msg = f"session {session_id!r} was stopped meanwhile; send the message again"
            raise SessionBusyError(msg)
        if live.busy or live.publishing:
            return await self._enqueue(live, session, text, attachments, interrupt, sender)
        require_cwd(session)
        live.start(
            lambda: self._turns.guard(live, self._send_turn(live, text, attachments, sender))
        )
        return SendResult(**session.model_dump())

    async def _enqueue(
        self,
        live: LiveSession,
        session: Session,
        text: str,
        attachments: list[Attachment],
        interrupt: bool,
        sender: Sender,
    ) -> SendResult:
        if not live.turn_active:
            live.held = True
        queued = await self._queue.add(session.id, text, attachments, interrupt, sender)
        if interrupt and live.nudgeable:
            live.resume_queue = True
            await self._approvals.expire(session.id, BLOCKING, "interrupted by the user")
            await live.interrupt()
        # What held the session may have ended while the message was stored (BUG-85).
        await self._turns.release_held(live)
        return SendResult(**session.model_dump(), queued_message=queued)

    async def _send_turn(
        self, live: LiveSession, text: str, attachments: list[Attachment], sender: Sender
    ) -> None:
        await self._approvals.supersede(live.session_id, ApprovalKind.REVIEW)
        await self._turns.submit(live, text, attachments, sender=sender)

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

    async def close_idle_run(self, session_id: str) -> None:
        """Close the session's agent run now if it is idle, as before the chat continues in
        Claude Code: a later message then resumes the conversation with what was done
        there (PL-15). A turn, background tasks or publishing in progress keep the run.
        """
        live = self._live.get(session_id)
        if live is None or live.busy or live.background_tasks or live.publishing:
            return
        live.cancel_idle_close()
        await live.close_run()

    async def update(self, session_id: str, request: UpdateSession) -> Session:
        """Rename, pin or archive; persist new controls and apply them to the live run.

        Archiving closes the agent run but keeps the worktree; a new message resumes it.
        """
        session = await self._store.get(session_id)
        if (request.model, request.permission_mode, request.effort) != (None, None, None):
            require_open(session)
            request = await self._fitting_mode(session, request)
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

    async def rewind(self, session_id: str, event_id: int, dry_run: bool) -> RewindResult:
        """Restore the files the agent changed since the user message of event `event_id`
        to how they were before it, or with `dry_run` say what that would change. Only
        while no turn runs (idle, interrupted or failed), in a chat that is not archived,
        not being published and has no background tasks running; the conversation stays
        as it is (IMP-02, BUG-104). A preview never starts Claude Code (BUG-94).
        """
        session = await self._store.get(session_id)
        if session.pixie_id is not None:
            # Each pixie run starts fresh, so an earlier run's checkpoints cannot be restored.
            raise PixieChatError(NO_PIXIE_RESTORE)
        require_open(session)
        checkpoint = await self._store.checkpoint(session_id, event_id)
        if checkpoint is None:
            result = RewindResult(can_rewind=False, error=NO_CHECKPOINT)
        else:
            require_workspace(session)
            await self._require_not_open_elsewhere(session)
            live = self._live.setdefault(session_id, LiveSession(session_id))
            problem = self._restore_problem(session, live)
            if problem is not None:
                raise SessionBusyError(problem)
            if dry_run and live.run is None:
                result = RewindResult(can_rewind=False, error=NO_RUN_TO_PREVIEW)
            else:
                result = await self._turns.rewind(live, checkpoint, dry_run)
        if dry_run:
            return result
        if not result.can_rewind:
            raise CannotRewindError(result.error or "the files could not be restored")
        await self._bus.publish(
            types.SESSION_NOTICE,
            {"kind": "files_restored", "text": _restored_text(result.files_changed)},
            session_id,
        )
        return result

    def _restore_problem(self, session: Session, live: LiveSession) -> str | None:
        """Why the chat's files cannot be restored now, in words for the user."""
        if session.archived_at is not None:
            return "Files cannot be restored in an archived chat. Unarchive it first."
        if self._stopping or live.stopped:
            return "This chat is being closed or archived, so its files cannot be restored."
        if live.busy:
            return (
                "Files can be restored only when no turn is running. Wait for the turn to "
                "end, or stop it."
            )
        if live.publishing:
            return (
                "Files cannot be restored while harness commits or pushes this chat's work. "
                "Try again when that is done."
            )
        if live.background_tasks:
            return (
                "Files cannot be restored while the agent's background tasks run. "
                "Wait for them to finish."
            )
        return None

    async def close(self, session_id: str, remove_worktree: bool) -> Session:
        require_open(await self._store.get(session_id))
        async with self._stopped(session_id, "the session was closed") as session:
            await self._queue.clear(session_id)
            worktree = worktree_of(session)
            if remove_worktree and worktree is not None:
                await self._worktrees.remove(
                    self._repos.get(session.repo), worktree, delete_branch=True
                )
            return await self._states.set(session_id, SessionState.CLOSED)

    async def close_keeping_work(self, session_id: str) -> bool:
        """Close the session; its worktree and branch are removed only when the worktree
        holds no work (B41). Returns whether a worktree with work was kept. Checked after
        the agent stopped, so it cannot add work meanwhile.
        """
        session = await self.close(session_id, remove_worktree=False)
        worktree = worktree_of(session)
        if worktree is None:
            return False
        if await self._worktrees.has_work(worktree):
            return True
        await self._worktrees.remove(self._repos.get(session.repo), worktree, delete_branch=True)
        return False

    async def purge(self, session_id: str) -> None:
        """Delete the session for good: its run, worktree and branch, and all it stored."""
        await self._store.get(session_id)
        async with self._stopped(session_id, "the session was deleted") as session:
            worktree = worktree_of(session)
            if worktree is not None:
                # Without the repo's config git cannot clean up; the rest is deleted anyway.
                with suppress(RepoNotFoundError):
                    repo = self._repos.get(session.repo)
                    await self._worktrees.remove(repo, worktree, delete_branch=True)
            await self._attachments.delete_files(session_id)
            await self._store.delete(session_id)
        await self._hooks.purged(session_id)
        # Not a session event: the session's events are gone with it.
        await self._bus.publish(types.SESSION_DELETED, {"session_id": session_id})

    @asynccontextmanager
    async def publishing(self, session_id: str) -> AsyncGenerator[None]:
        """Hold new turns off while the daemon commits, pushes or merges the session's work
        (BUG-14): a message sent meanwhile is queued and starts afterwards, and a turn the
        agent starts on its own waits. A queue held by a Stop keeps waiting (BUG-61).
        """
        await self._store.get(session_id)
        live = self._live.setdefault(session_id, LiveSession(session_id))
        live.published.clear()
        try:
            yield
        finally:
            live.published.set()
            if self._live.get(session_id) is live:
                await self._turns.release_held(live)

    async def audit_refs(self, session_id: str) -> None:
        """Check what the publish uses right before the daemon publishes: HEAD, the branch
        it names and that branch. A background command of the agent may have changed them
        after the last turn's audit (D013 layer 4). A change sets `git_violation`. Other
        refs, such as other chats' branches or those a fetch moves, are left to the next
        turn-end audit (BUG-51). Without an audit in this process (after a restart) there
        is nothing to compare with, and the refs as they are become the baseline.
        """
        live = self._live.setdefault(session_id, LiveSession(session_id))
        await self._turns.audit(live, publishing=True)

    async def set_git_violation(self, session_id: str, flagged: bool) -> Session:
        """Flag what the agent did with git for the user to acknowledge, or clear the flag
        once the user published anyway (BUG-50, BUG-51).
        """
        return await set_git_violation(self._store, self._bus, session_id, flagged)

    def background_running(self, session_id: str) -> bool:
        """Whether the agent reports background tasks running in this process (BUG-57)."""
        live = self._live.get(session_id)
        return live is not None and live.background_tasks > 0

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
        self._stopping = True
        lives = list(self._live.values())
        self._live.clear()
        # One session's failure must not leave the others running or skip the rest of
        # the daemon's shutdown.
        results = await asyncio.gather(
            *(self._shut_down(live, "the daemon stopped") for live in lives),
            return_exceptions=True,
        )
        for live, result in zip(lives, results, strict=True):
            if isinstance(result, Exception):
                logger.error("stopping session %s failed", live.session_id, exc_info=result)

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

    @asynccontextmanager
    async def _stopped(self, session_id: str, reason: str) -> AsyncGenerator[Session]:
        """Expire everything pending and stop the agent, then yield the session as it is
        now. Until the block ends (the session is closed or deleted), its live state stays,
        marked stopped, so a message sent meanwhile is refused instead of starting a new
        run (BUG-53).
        """
        live = self._live.setdefault(session_id, LiveSession(session_id))
        live.stopped = True
        try:
            await self._approvals.expire(session_id, tuple(ApprovalKind), reason)
            await live.stop()
            # Read again: setup may have created the worktree while the session was starting.
            yield await self._store.get(session_id)
        finally:
            self._forget(live)

    async def _release(self, session_id: str, reason: str) -> None:
        """Stop the agent of a session that stays open; the next message starts a new run."""
        live = self._live.get(session_id)
        if live is None:
            return
        live.stopped = True
        try:
            await self._shut_down(live, reason)
        finally:
            self._forget(live)

    def _forget(self, live: LiveSession) -> None:
        if self._live.get(live.session_id) is live:
            del self._live[live.session_id]

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
        return await save_changes(self._store, self._bus, session_id, changes)

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

    async def _fitting_mode(self, session: Session, request: UpdateSession) -> UpdateSession:
        """`request`, refused (422) when its model and mode do not fit (`fitting_mode`)."""
        mode = await self.fitting_mode(
            request.model or session.model,
            request.permission_mode,
            session.permission_mode,
            model_changed=request.model is not None,
        )
        return request.model_copy(update={"permission_mode": mode})

    async def fitting_mode(
        self,
        model: str | None,
        chosen: PermissionMode | None,
        current: PermissionMode,
        *,
        model_changed: bool,
    ) -> PermissionMode | None:
        """The mode to save as a chat's or pixie's model and mode change: `chosen`,
        refused (422) when `model` does not run in it. With none chosen, one in Auto moved
        to a model without it asks again (`default`) instead (BUG-86); otherwise None,
        which keeps the mode it has.
        """
        if (
            model_changed
            and chosen is None
            and current == AUTO
            and await self._mode_problem(model, AUTO)
        ):
            return DEFAULT_MODE
        await self._require_mode(model, chosen)
        return chosen

    async def _require_mode(self, model: str | None, mode: PermissionMode | None) -> None:
        """422 when the engine's list knows the model and it does not run in `mode`."""
        problem = await self._mode_problem(model, mode)
        if problem is not None:
            raise InvalidInputError(problem)

    async def _mode_problem(self, model: str | None, mode: PermissionMode | None) -> str | None:
        """Why `model` does not run in `mode`; None when it does or the list is unknown."""
        option = None if self._models is None else await self._models(model)
        return None if option is None else mode_problem(option, mode)

    def _handler_for(self, live: LiveSession) -> ApprovalHandler:
        async def on_mode(_session_id: str, mode: PermissionMode) -> None:
            await self._engine_mode(live, mode)

        return SessionPrompts(
            live.session_id, self._approvals, self._store, self._on_waiting, on_mode
        )

    async def _engine_mode(self, live: LiveSession, mode: PermissionMode) -> None:
        """The agent's engine reported its mode: the one Claude Code's own settings chose,
        an approved plan's, or a switch it made. The run has it now, and the session
        records and announces it. The mode the run already has is harness's own change
        echoed back: a newer choice saved meanwhile stays (BUG-62).
        """
        if mode == live.run_mode:
            return
        live.run_mode = mode
        if mode == BYPASS:
            # Opened in bypass by Claude Code's own setting: it may switch back live (D046).
            live.run_bypass = True
        session = await self._store.get(live.session_id)
        changes: dict[str, object] = {}
        if session.permission_mode != mode:
            changes["permission_mode"] = mode
        if session.follows_claude_code_mode:
            changes["follows_claude_code_mode"] = False
        if changes:
            await self._save_changes(live.session_id, changes)

    async def _on_waiting(self, session_id: str, waiting: bool) -> None:
        live = self._live.get(session_id)
        if live is None or live.stopped:
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


def _restored_text(files: list[str]) -> str:
    if not files:
        return "Restored files to before your message"
    count = "1 file" if len(files) == 1 else f"{len(files)} files"
    return f"Restored {count} to before your message"
