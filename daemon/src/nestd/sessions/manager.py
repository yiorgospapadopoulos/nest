"""Session lifecycle commands: create, send, interrupt, update, close, purge.

Each session has at most one background task (setup plus the first turn, or a later turn),
so turns are serialized: a message sent while one runs goes into that turn when the agent
can take it (B59), else it is queued and starts the next turn once this one ends (D032).
"""

import asyncio
import logging
from collections.abc import AsyncGenerator, Callable, Sequence
from contextlib import asynccontextmanager, suppress
from datetime import timedelta
from pathlib import Path

from nestd.approvals.models import BLOCKING, ApprovalKind
from nestd.approvals.queue import ApprovalQueue
from nestd.attachments.store import Attachment, AttachmentStore
from nestd.claude_sessions.errors import ChatOpenElsewhereError
from nestd.claude_sessions.live import LiveChats
from nestd.clock import Clock
from nestd.config.models import AgentDefaults, Effort, PermissionMode, RepoConfig, SessionMode
from nestd.engine.models import closest_effort
from nestd.engine.service import effort_problem, mode_problem
from nestd.errors import InvalidInputError
from nestd.events import types
from nestd.events.bus import EventBus
from nestd.providers.base import AgentProvider, ApprovalHandler
from nestd.repos.service import RepoNotFoundError, RepoService, require_folder
from nestd.sessions.engines import DefaultModel, Engine, Engines, ModelLookup
from nestd.sessions.errors import (
    CannotRewindError,
    NoAgentRunError,
    NotPausedError,
    NoTurnInProgressError,
    NoWorkspaceError,
    PixieChatError,
    PixieInTeamError,
    SessionBusyError,
    TaskNotFoundError,
)
from nestd.sessions.extras import NestToolsSource, RunExtrasSource
from nestd.sessions.files import FileIndex
from nestd.sessions.hooks import SessionHooks
from nestd.sessions.limits import ClearReason, LimitPauses
from nestd.sessions.live import BYPASS, LiveSession
from nestd.sessions.models import (
    USER,
    ChatImport,
    CreateSession,
    ForkReply,
    NewSession,
    QueuedMessage,
    Restore,
    RewindReply,
    Sender,
    SendResult,
    Session,
    SessionState,
    UpdateSession,
    pixie_repo,
)
from nestd.sessions.prompts import SessionPrompts
from nestd.sessions.queue import MessageQueue
from nestd.sessions.rewinds import NO_CHECKPOINT, NO_PIXIE_RESTORE, Rewinds
from nestd.sessions.rules import (
    require_cwd,
    require_open,
    require_workspace,
    session_changes,
    worktree_of,
)
from nestd.sessions.states import StateWriter
from nestd.sessions.store import SessionStore
from nestd.sessions.subagents import CallToolsSource, ChatAgentsSource, PixieCalls
from nestd.sessions.titles import short_title
from nestd.sessions.turns import TurnRunner
from nestd.sessions.updates import save_changes
from nestd.worktrees.manager import WorktreeManager

# Ask: a chat's mode when none is chosen or fits (B94); before B94 also what a session
# following Claude Code's own mode showed until the engine reported it.
DEFAULT_MODE: PermissionMode = "default"
AUTO: PermissionMode = "auto"

# How often the daemon checks for chats whose usage limit pause is over (B78).
LIMIT_TICK = timedelta(seconds=5)
# What a chat paused at the usage limit is sent when it goes on with nothing queued (B78).
CONTINUE_TEXT = "Continue where you left off."
LIMIT_RESUME = Sender(origin="limit_resume")

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
        default_model: DefaultModel | None = None,
        extras: RunExtrasSource | None = None,
        agents: ChatAgentsSource | None = None,
        calls: PixieCalls | None = None,
        nest_tools: NestToolsSource | None = None,
        call_tools: CallToolsSource | None = None,
        engines: Sequence[Engine] = (),
    ) -> None:
        """`defaults` is read for each new session, so edits apply at once; `models`
        checks a new session's effort against its model (D038). `calls` follows the pixies
        a project chat calls (B46); `nest_tools` are the tools of every run (B79);
        `call_tools` call the pixies a run calls as sessions of their own (B91).
        `provider` and `models` are the default engine's; `engines` the others a chat
        can ask for, such as Codex (B91).
        """
        self._engines = Engines(Engine(provider, models, default=default_model), engines)
        self._queue = queue
        self._files = files or FileIndex(clock)
        self._clock = clock
        self._live_chats = live_chats
        self._store = store
        self._bus = bus
        self._repos = repos
        self._worktrees = worktrees
        self._attachments = attachments
        self._approvals = approvals
        self._defaults = defaults
        self._hooks = hooks
        self._states = StateWriter(store, bus, hooks)
        self._limits = LimitPauses(store, bus, clock)
        self._limit_task: asyncio.Task[None] | None = None
        self._turns = TurnRunner(
            store=store,
            bus=bus,
            states=self._states,
            hooks=hooks,
            worktrees=worktrees,
            repos=repos,
            attachments=attachments,
            engines=self._engines,
            handler_for=self._handler_for,
            on_mode=self._engine_mode,
            idle_close=idle_close,
            queue=queue,
            clock=clock,
            limits=self._limits,
            extras=extras,
            agents=agents,
            calls=calls,
            nest_tools=nest_tools,
            call_tools=call_tools,
        )
        self._rewinds = Rewinds(
            store=store,
            bus=bus,
            engines=self._engines,
            turns=self._turns,
            hooks=hooks,
            repos=repos,
            worktrees=worktrees,
            attachments=attachments,
        )
        self._live: dict[str, LiveSession] = {}
        # Set when the daemon stops its agents: no message starts a turn after that.
        self._stopping = False

    @property
    def engines(self) -> Engines:
        """The engines chats can run on (B91)."""
        return self._engines

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
        engine = (
            self._engines.named(request.provider)
            if request.provider is not None
            else await self._engines.listing(request.model, self._defaults_engine(defaults))
        )
        await engine.require_ready()
        # The defaults are their engine's; another engine starts on its own default model,
        # Medium (or the closest level) and Ask (B91, B94).
        own = engine is self._defaults_engine(defaults)
        model = request.model or (defaults.model if own else None) or await engine.default_model()
        effort = await self._effort(engine, model, request.effort, defaults.effort if own else None)
        permission_mode = request.permission_mode
        await self._require_mode(engine, model, permission_mode)
        # A default mode the model does not run in is dropped, as the effort default is.
        if permission_mode is None and not await self._mode_problem(
            engine, model, defaults.permission_mode
        ):
            permission_mode = defaults.permission_mode
        # A plain folder has no worktrees or branches: its chats always work in place (D041).
        mode = (
            (request.mode or _repo_mode(repo) or defaults.default_mode) if repo.git else "in_place"
        )
        base_ref = await self._worktree_start(repo, mode, request)
        new = NewSession(
            repo=repo.name,
            title=request.title or short_title(request.prompt),
            prompt=request.prompt,
            mode=mode,
            cwd=repo.path if mode == "in_place" else None,
            model=model,
            effort=effort,
            # Nest always passes the mode; Ask when none fits (B94).
            permission_mode=permission_mode or DEFAULT_MODE,
            follows_claude_code_mode=False,
            provider=engine.name,
            base_ref=base_ref,
            started_by_pixie=started_by_pixie,
            pixie_batch=pixie_batch,
        )
        await self._refuse_member_calls(new, request.prompt)
        attachments = await self._attachments.for_session(request.attachment_ids, None)
        session = await self._store.create(new, branch=request.branch)
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

    async def _worktree_start(
        self, repo: RepoConfig, mode: SessionMode, request: CreateSession
    ) -> str | None:
        """The new session's base: HEAD for an in-place chat; for a worktree chat, the
        commit of the `base` branch asked for, else None until the worktree is created.
        Checks the branch name asked for (B55).
        """
        if mode == "in_place":
            if request.branch is not None or request.base is not None:
                msg = "a branch and a base are only for a new worktree chat"
                raise InvalidInputError(msg)
            return await self._worktrees.head(repo)
        if request.branch is not None:
            await self._worktrees.check_new_branch(repo, request.branch)
        if request.base is None:
            return None
        return await self._worktrees.branch_commit(repo, request.base)

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
        provider: str | None = None,
        called_by: str | None = None,
    ) -> Session:
        """A pixie's chat: in place in its workdir, with no project, review or git (D072).
        Refused (422) when the model does not run in the pixie's mode, as for any chat.
        With `habit_run_id` it is the session of one run of the pixie's habit (B42); with
        `called_by`, the pixie called from that chat, in `cwd`, the caller's folder (B91).
        `provider` is the pixie's engine (None: the default), which must be ready (409).
        """
        engine = self._engines.default if provider is None else self._engines.by_name(provider)
        await engine.require_ready()
        await self._require_mode(engine, model, permission_mode)
        attachments = await self._attachments.for_session(attachment_ids, None)
        session = await self._store.create(
            NewSession(
                repo=pixie_repo(pixie_id),
                title=title,
                prompt=prompt,
                mode="in_place",
                cwd=cwd,
                model=model,
                effort=await self._effort(engine, model, effort, None),
                permission_mode=permission_mode,
                provider=engine.name,
                pixie_id=pixie_id,
                habit_run_id=habit_run_id,
                called_by=called_by,
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
        chat through the engine. Nest never removes that folder (no worktree is set).
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
        engine = self._engines.default
        # The defaults apply when they are Claude's; else Claude's own default model.
        own = engine is self._defaults_engine(defaults)
        model = (defaults.model if own else None) or await engine.default_model()
        mode = defaults.permission_mode if own else None
        if await self._mode_problem(engine, model, mode):
            mode = None
        created = await self._store.create(
            NewSession(
                repo=repo.name,
                title=chat.title,
                prompt=chat.prompt,
                mode="in_place",
                cwd=chat.cwd,
                model=model,
                effort=await self._effort(engine, model, None, defaults.effort if own else None),
                permission_mode=mode or DEFAULT_MODE,
                follows_claude_code_mode=False,
                provider=engine.name,
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
        A pending review of the session's work stays: only a turn that changes the work
        replaces it (B56). While the daemon publishes the work, the message is queued and
        starts once that is done.
        """
        session = await self._store.get(session_id)
        require_open(session)
        await self._engines.of(session).require_ready()
        await self._refuse_member_calls(session, text)
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
        if live.busy or live.publishing or self._limits.paused(session_id):
            # Paused at the usage limit, it waits until the limit resets (B78).
            return await self._enqueue(live, session, text, attachments, interrupt, sender)
        if _forked_worktree(session):
            # A forked worktree chat gets its worktree with its first message (B59); a
            # chat whose worktree could not be made has failed instead.
            repo = self._repos.get(session.repo)
            live.start(
                lambda: self._turns.guard(
                    live,
                    self._turns.start_later(live, session, repo, attachments, sender, text),
                )
            )
            return SendResult(**session.model_dump())
        require_cwd(session)
        live.start(
            lambda: self._turns.guard(
                live, self._turns.submit(live, text, attachments, sender=sender)
            )
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
        if not interrupt:
            steered = await self._turns.steering.send(live, text, attachments, sender)
            if steered is not None:
                return SendResult(**session.model_dump(), queued_message=steered)
        if not live.turn_active:
            live.held = True
        queued = await self._queue.add(session.id, text, attachments, interrupt, sender)
        if interrupt and live.nudgeable:
            await self._nudge(live)
        # What held the session may have ended while the message was stored (BUG-85).
        await self._turns.release_held(live)
        return SendResult(**session.model_dump(), queued_message=queued)

    async def queued(self, session_id: str) -> list[QueuedMessage]:
        await self._store.get(session_id)
        return await self._queue.messages(session_id)

    async def cancel_queued(self, session_id: str, message_id: str) -> None:
        """Remove a queued message; one written into the turn only until the agent reads
        it (409 `message_taken`, B59).
        """
        await self._store.get(session_id)
        await self._turns.steering.remove(self._live.get(session_id), session_id, message_id)

    async def send_now(self, session_id: str, message_id: str) -> None:
        """Send a queued message now, like Claude Code's Send now: it goes first, and a
        running turn is stopped so it starts right after, as a nudge does (D036). On an
        idle session it starts at once; while the work is published or a restore holds the
        session it waits, first in line. One the agent already read stays in its turn (B59).
        """
        session = await self._store.get(session_id)
        require_open(session)
        await self._queue.make_urgent(session_id, message_id)
        # The user's choice to send now ends a usage limit pause (B78).
        await self._limits.clear(session_id, "resumed")
        live = self._live.setdefault(session_id, LiveSession(session_id))
        if live.nudgeable:
            await self._nudge(live, message_id)
        elif not live.busy and not live.publishing and not live.stopped and not self._stopping:
            await self._require_not_open_elsewhere(session)
            require_cwd(session)
            live.start(lambda: self._turns.guard(live, self._turns.deliver_next(live)))

    async def _nudge(self, live: LiveSession, message_id: str | None = None) -> None:
        """Stop the turn so the queue's first message starts right after it. Messages in
        the turn the agent has not read wait in the queue again; when it already read
        `message_id`, the turn goes on (B59).
        """
        async with live.steering:
            taken = await self._turns.steering.retract(live)
            if message_id is not None and message_id in taken:
                return
            live.resume_queue = True
            await self._approvals.expire(live.session_id, BLOCKING, "interrupted by the user")
            await live.interrupt()

    async def files(self, session_id: str, query: str) -> list[str]:
        """Files in the session's working directory matching `query`, for @ mentions."""
        session = await self._store.get(session_id)
        cwd = require_workspace(session)
        if session.pixie_id is not None or not await self._repos.has_git(session.repo):
            return await self._files.search(cwd, query, git=False)
        return await self._files.search(cwd, query)

    async def interrupt(self, session_id: str) -> None:
        """Stop the turn. Messages written into it that the agent has not read are taken
        back first, so they wait for the next turn instead of running after the Stop (B59).
        A chat paused at the usage limit stops going on: the pause ends and its messages
        wait, as after any Stop (B78).
        """
        await self._store.get(session_id)
        await self._approvals.expire(session_id, BLOCKING, "interrupted by the user")
        live = self._live.get(session_id)
        stopped = False
        if live is not None:
            async with live.steering:
                await self._turns.steering.retract(live)
                stopped = await live.interrupt()
        if await self._end_pause(session_id, "stopped", turn_stopped=stopped):
            return
        if not stopped:
            msg = f"session {session_id!r} has no turn in progress"
            raise NoTurnInProgressError(msg)

    async def stop_task(self, session_id: str, task_id: str) -> None:
        """Stop one running task of the session's agent, a background command or a
        subagent, without stopping the turn; its end arrives as a task event (B59).
        """
        self._engines.of(await self._store.get(session_id)).require("stop_task")
        live = self._live.get(session_id)
        run = live.run if live is not None else None
        if run is None:
            msg = f"session {session_id!r} has no agent running"
            raise NoAgentRunError(msg)
        if not await run.stop_task(task_id):
            msg = f"session {session_id!r} has no running task {task_id!r}"
            raise TaskNotFoundError(msg)

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
            await self._end_pause(session_id, "archived")
        session = await self._save_changes(session_id, changes)
        live = self._live.get(session_id)
        if live is not None and {"model", "permission_mode"} & changes.keys():
            # Read back from the store, so of two quick changes the last one wins (D048).
            await self._turns.apply_controls(live)
        return session

    async def rewind(
        self, session_id: str, event_id: int, dry_run: bool, restore: Restore = "code"
    ) -> RewindReply:
        """Rewind the chat to before the user message of event `event_id`, as Claude Code
        does: the files the agent changed since (`code`, IMP-02), the conversation (that
        message and all after it leave the chat; its text comes back for the composer,
        B59), or both; with `dry_run` say what that would do. Only while no turn runs
        (idle, interrupted or failed), in a chat that is not archived, not being published
        and has no background tasks running (BUG-104). A preview never starts Claude Code
        (BUG-94).
        """
        session = await self._store.get(session_id)
        if session.pixie_id is not None:
            # Each pixie run starts fresh, so an earlier run's checkpoints cannot be restored.
            raise PixieChatError(NO_PIXIE_RESTORE)
        self._engines.of(session).require("rewind")
        require_open(session)
        checkpoint = await self._store.checkpoint(session_id, event_id)
        message = await self._rewinds.user_message(session_id, event_id)
        if checkpoint is None or message is None:
            if dry_run:
                return RewindReply(can_rewind=False, error=NO_CHECKPOINT, restore=restore)
            raise CannotRewindError(NO_CHECKPOINT)
        require_workspace(session)
        await self._require_not_open_elsewhere(session)
        live = self._live.setdefault(session_id, LiveSession(session_id))
        problem = self._restore_problem(session, live)
        if problem is not None:
            raise SessionBusyError(problem)
        if dry_run:
            return await self._rewinds.preview(live, session, message, checkpoint, restore)
        return await self._rewinds.rewind(live, session, message, checkpoint, restore)

    async def fork(self, session_id: str, event_id: int) -> ForkReply:
        """A new chat whose conversation is this one's up to before the user message of
        event `event_id`, in the same project and work mode; this chat stays as it is
        (B59). Refused while a turn runs, in a pixie's chat, and for a message Nest has no
        checkpoint for.
        """
        source = await self._store.get(session_id)
        if source.pixie_id is not None:
            raise PixieChatError("A pixie's chat cannot be forked.")
        self._engines.of(source).require("fork")
        require_open(source)
        try:
            require_folder(self._repos.get(source.repo))
        except RepoNotFoundError as error:
            raise InvalidInputError(str(error)) from error
        if self.busy(session_id):
            msg = "A chat can be forked only when no turn is running. Wait for it, or stop it."
            raise SessionBusyError(msg)
        checkpoint = await self._store.checkpoint(session_id, event_id)
        message = await self._rewinds.user_message(session_id, event_id)
        if checkpoint is None or message is None:
            raise CannotRewindError(NO_CHECKPOINT)
        return await self._rewinds.fork(source, message, checkpoint)

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
                "Files cannot be restored while Nest commits or pushes this chat's work. "
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
            await self._limits.clear(session_id, "closed")
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
        self._limits.forget(session_id)
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

    def background_running(self, session_id: str) -> bool:
        """Whether the agent reports background tasks running in this process (BUG-57)."""
        live = self._live.get(session_id)
        return live is not None and live.background_tasks > 0

    async def recover(self) -> None:
        """On startup, turns cut off by the previous process can only be resumed, and
        messages written into them wait for a turn again (B59).
        """
        await self._queue.unsend_all()
        for session_id in await self._store.interrupt_in_flight():
            await self._bus.publish(
                types.SESSION_STATE, {"state": SessionState.INTERRUPTED, "error": None}, session_id
            )
        await self._limits.load()

    async def start(self, tick: timedelta = LIMIT_TICK) -> None:
        """Go on with the chats paused at the usage limit when their time comes; those
        whose time passed while the daemon was down go on at once (B78).
        """
        self._limit_task = asyncio.create_task(self._limit_loop(tick))

    async def _limit_loop(self, tick: timedelta) -> None:
        while True:
            await self.tick_limits()
            await asyncio.sleep(tick.total_seconds())

    async def tick_limits(self) -> None:
        """Go on with every paused chat whose time has come (B78). One that Claude Code has
        open elsewhere is left to it: its pause ends, and its messages wait.
        """
        for session_id in self._limits.take_due(self._clock.now()):
            try:
                await self._limits.cleared(session_id, "reset")
                await self._require_not_open_elsewhere(await self._store.get(session_id))
                await self._go_on(session_id)
            except Exception as error:
                logger.warning(
                    "going on with session %s after the usage limit failed (%s)", session_id, error
                )

    async def resume_limit(self, session_id: str) -> Session:
        """Resume now: end the chat's usage limit pause and go on at once (B78). A limit
        that still holds pauses it again. 409 when it is not paused.
        """
        session = await self._store.get(session_id)
        require_open(session)
        await self._require_not_open_elsewhere(session)
        require_cwd(session)
        if not await self._limits.clear(session_id, "resumed"):
            msg = f"session {session_id!r} is not paused at the usage limit"
            raise NotPausedError(msg)
        await self._go_on(session_id)
        return await self._store.get(session_id)

    async def _go_on(self, session_id: str) -> None:
        """After a usage limit pause: the queued messages in their order, else the message
        that lets Claude continue, shown as Nest's (B78). A turn in progress starts the
        queue at its end; one held by publishing, once that is done.
        """
        live = self._live.setdefault(session_id, LiveSession(session_id))
        if self._stopping or live.stopped or live.busy:
            return
        if not await self._queue.waiting(session_id):
            await self._queue.add(session_id, CONTINUE_TEXT, [], sender=LIMIT_RESUME)
        live.held = True
        await self._turns.release_held(live)

    async def _end_pause(
        self, session_id: str, reason: ClearReason, turn_stopped: bool = False
    ) -> bool:
        """End the chat's usage limit pause without going on: its messages wait, as after
        a Stop, and the chat shows interrupted unless a turn it stopped ends so (B78).
        False when it was not paused.
        """
        if not await self._limits.clear(session_id, reason):
            return False
        live = self._live.get(session_id)
        if live is not None:
            live.held = False
        if not turn_stopped:
            await self._states.set(session_id, SessionState.INTERRUPTED)
        return True

    async def shutdown(self) -> None:
        """Stop every agent. A turn cut off here is interrupted, as after a hard kill. Usage
        limit pauses stay for the next start (B78).
        """
        self._stopping = True
        task, self._limit_task = self._limit_task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
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

    async def _refuse_member_calls(self, session: NewSession, text: str) -> None:
        """422 for a message that calls a pixie of a team on its own: a team's pixies are
        called only with their team (B46). A pixie's chat offers no teams.
        """
        problem = (await self._turns.chat_agents(session)).member_call(text)
        if problem is not None:
            raise PixieInTeamError(problem)

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
        # The agent is gone; what was written into its turn waits for a turn again (B59).
        await self._queue.unsend_all(live.session_id)
        if live.turn_active:
            live.turn_active = False
            duration = live.turn_ms(self._clock.now())
            await self._states.set(
                live.session_id, SessionState.INTERRUPTED, turn={"duration_ms": duration}
            )

    async def _save_changes(self, session_id: str, changes: dict[str, object]) -> Session:
        return await save_changes(self._store, self._bus, session_id, changes)

    async def _effort(
        self, engine: Engine, model: str | None, chosen: Effort | None, default: Effort | None
    ) -> Effort | None:
        """The chosen effort, refused (422) when the model does not take it; the default
        effort only when the model takes it; else Medium or the closest level the model
        takes (B94). Unchecked while the model list is unknown.
        """
        option = await engine.find(model)
        if option is None:
            return chosen or default
        if chosen is not None:
            problem = effort_problem(option, chosen)
            if problem is not None:
                raise InvalidInputError(problem)
            return chosen
        if default is not None and effort_problem(option, default) is None:
            return default
        return closest_effort(option.effort_levels)

    def _defaults_engine(self, defaults: AgentDefaults) -> Engine:
        """The agent defaults' engine; the default one when they name none (B94)."""
        if defaults.provider is None:
            return self._engines.default
        return self._engines.by_name(defaults.provider)

    async def _fitting_mode(self, session: Session, request: UpdateSession) -> UpdateSession:
        """`request`, refused (422) when its model and mode do not fit (`fitting_mode`)."""
        mode = await self.fitting_mode(
            request.model or session.model,
            request.permission_mode,
            session.permission_mode,
            model_changed=request.model is not None,
            engine=self._engines.of(session),
        )
        return request.model_copy(update={"permission_mode": mode})

    async def fitting_mode(
        self,
        model: str | None,
        chosen: PermissionMode | None,
        current: PermissionMode,
        *,
        model_changed: bool,
        engine: Engine | None = None,
    ) -> PermissionMode | None:
        """The mode to save as a chat's or pixie's model and mode change: `chosen`,
        refused (422) when `model` does not run in it. With none chosen, one in Auto moved
        to a model without it asks again (`default`) instead (BUG-86); otherwise None,
        which keeps the mode it has. `engine` is the chat's, None the default one.
        """
        engine = engine or self._engines.default
        if (
            model_changed
            and chosen is None
            and current == AUTO
            and await self._mode_problem(engine, model, AUTO)
        ):
            return DEFAULT_MODE
        await self._require_mode(engine, model, chosen)
        return chosen

    async def _require_mode(
        self, engine: Engine, model: str | None, mode: PermissionMode | None
    ) -> None:
        """422 when the engine's list knows the model and it does not run in `mode`."""
        problem = await self._mode_problem(engine, model, mode)
        if problem is not None:
            raise InvalidInputError(problem)

    async def _mode_problem(
        self, engine: Engine, model: str | None, mode: PermissionMode | None
    ) -> str | None:
        """Why `model` does not run in `mode`; None when it does or the list is unknown."""
        option = await engine.find(model)
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
        records and announces it. The mode the run already has is Nest's own change
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


def _forked_worktree(session: Session) -> bool:
    """An idle worktree chat without its worktree yet: a fork (B59)."""
    return (
        session.mode == "worktree"
        and session.worktree_path is None
        and session.state is SessionState.IDLE
    )


def _repo_mode(repo: RepoConfig) -> SessionMode | None:
    """The repo's own choice, when its config sets `[worktree] default`."""
    if repo.worktree.default is None:
        return None
    return "worktree" if repo.worktree.default else "in_place"
