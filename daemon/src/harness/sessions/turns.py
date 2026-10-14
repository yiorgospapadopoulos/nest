"""A session's background work: setup, turns on the agent run, and the post-turn git audit."""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Coroutine
from datetime import timedelta
from pathlib import Path
from typing import Any

from harness.attachments.store import Attachment, AttachmentStore
from harness.clock import Clock
from harness.config.models import PermissionMode, RepoConfig
from harness.events import types
from harness.events.bus import EventBus
from harness.providers.base import (
    AgentProvider,
    AgentRun,
    ApprovalHandler,
    RewindResult,
    SessionSpec,
)
from harness.repos.service import RepoService
from harness.sessions.bookkeeping import isolated
from harness.sessions.git_audit import changed_refs, for_publish, snapshot_refs
from harness.sessions.hooks import SessionHooks
from harness.sessions.live import BYPASS, LiveSession, Unsent
from harness.sessions.models import Session, SessionState
from harness.sessions.queue import MessageQueue
from harness.sessions.rules import attachment_summary, require_cwd, user_input
from harness.sessions.sink import SessionSink
from harness.sessions.states import StateWriter
from harness.sessions.store import SessionStore
from harness.sessions.updates import set_git_violation
from harness.sessions.workspace import prepare_worktree
from harness.worktrees.manager import WorktreeManager

logger = logging.getLogger(__name__)

# How long the turn's end waits for the context report, which holds up harness's reader
# of the agent's messages. The SDK takes control answers in its own reader, which stops
# only once 100 messages wait unread (I-L).
CONTROL_TIMEOUT_SECONDS = 10.0

_CONNECTORS_NOTE = (
    "Mention MCP servers that need authorization or failed to connect only when the user "
    "asks about them or the task needs one of them."
)
HARNESS_PROMPT = (
    "You are running inside harness. Do not run git commit, git push, gh pr create or "
    "gh pr merge: harness commits, pushes and opens pull requests after the user approves "
    f"your work. {_CONNECTORS_NOTE}"
)
# A plain folder's work is never reviewed, committed or pushed (D041).
PLAIN_FOLDER_PROMPT = (
    "You are running inside harness, in a folder that is not a git repository. Do not run "
    f"git commit, git push, gh pr create or gh pr merge. {_CONNECTORS_NOTE}"
)

# The state a background task ends in, and the error that caused it, if any.
type Outcome = tuple[SessionState, str | None]


class TurnRunner:
    """Runs a session's tasks and follows the agent's turns as its run reports them."""

    def __init__(
        self,
        *,
        store: SessionStore,
        bus: EventBus,
        states: StateWriter,
        hooks: SessionHooks,
        worktrees: WorktreeManager,
        repos: RepoService,
        attachments: AttachmentStore,
        provider: AgentProvider,
        handler_for: Callable[[LiveSession], ApprovalHandler],
        on_mode: Callable[[LiveSession, PermissionMode], Awaitable[None]],
        idle_close: timedelta,
        queue: MessageQueue,
        clock: Clock,
    ) -> None:
        """`on_mode` records a permission mode the engine switched to itself."""
        self._on_mode = on_mode
        self._repos = repos
        self._queue = queue
        self._clock = clock
        self._store = store
        self._bus = bus
        self._states = states
        self._hooks = hooks
        self._worktrees = worktrees
        self._attachments = attachments
        self._provider = provider
        self._handler_for = handler_for
        self._idle_close = idle_close

    async def guard(self, live: LiveSession, work: Coroutine[Any, Any, Outcome | None]) -> None:
        """Run `work` as the session's task. An outcome ends the turn; None means the
        message was submitted and the agent's result will end it.
        """
        outcome: Outcome | None = (SessionState.INTERRUPTED, None)  # if cancelled
        try:
            outcome = await work
        except Exception as exc:
            logger.exception("session %s failed", live.session_id)
            await live.close_run()
            outcome = (SessionState.FAILED, str(exc))
        finally:
            # A queued message may already have started the next task; that one stays.
            if live.task is asyncio.current_task():
                live.task = None
            if outcome is not None:
                await self._conclude(live, *outcome)
            else:
                # The turn may have ended while its message was still being sent, and a
                # message sent since then waited only for this task (BUG-60).
                live.schedule_idle_close(self._idle_close)
                await self.release_held(live)

    async def start(
        self, live: LiveSession, session: Session, repo: RepoConfig, attachments: list[Attachment]
    ) -> Outcome | None:
        if session.mode == "worktree":
            live.preparing = True
            try:
                setup = await prepare_worktree(
                    session, repo, self._worktrees, self._store, self._bus
                )
            except asyncio.CancelledError:
                _keep_unsent(live, Unsent(session.prompt, attachments, shown=False))
                raise
            finally:
                live.preparing = False
            if not setup.ok:
                return SessionState.FAILED, f"setup command failed: {setup.command}"
        return await self.submit(live, session.prompt, attachments)

    async def submit(
        self, live: LiveSession, text: str, attachments: list[Attachment], shown: bool = False
    ) -> None:
        """Show the message unless it is `shown` already, and give it to the agent. A nudge
        that cuts it off before the agent has it keeps it to go first (BUG-58).
        """
        try:
            if not shown:
                await self._announce(live, text, attachments)
                shown = True
            await self._run_turn(live, text, attachments)
        except asyncio.CancelledError:
            if not live.turn_active:
                _keep_unsent(live, Unsent(text, attachments, shown))
            raise

    async def _announce(self, live: LiveSession, text: str, attachments: list[Attachment]) -> None:
        session_id = live.session_id
        await self._attachments.assign([a.id for a in attachments], session_id)
        event = await self._bus.publish(
            types.SESSION_USER_MESSAGE,
            {"text": text, "attachments": [attachment_summary(a) for a in attachments]},
            session_id,
        )
        live.user_event = event.id

    async def _run_turn(self, live: LiveSession, text: str, attachments: list[Attachment]) -> None:
        session = await self._start_turn(live)
        cwd = require_cwd(session)
        run = await self._ensure_run(live, session, cwd)
        live.baseline = await snapshot_refs(cwd)
        live.turn_active = True
        await run.send(user_input(text, attachments))

    async def agent_active(self, live: LiveSession) -> None:
        # A turn the agent starts on its own waits while the daemon publishes its work or
        # files are restored (BUG-89).
        await live.published.wait()
        await live.unheld.wait()
        if live.busy:
            return
        # The agent started a turn on its own, e.g. after a background task finished.
        live.turn_active = True
        live.cancel_idle_close()
        await self._start_turn(live)

    async def _start_turn(self, live: LiveSession) -> Session:
        """The agent gets a message or starts on its own; clients time the turn from here."""
        live.turn_started = self._clock.now()
        return await self._states.set(
            live.session_id, SessionState.RUNNING, turn={"turn_start": True}
        )

    async def turn_finished(self, live: LiveSession, error: str | None) -> None:
        """Audit and report the turn, then end it or deliver the next queued message.
        The audit and reports are bookkeeping: their failure never keeps the turn open.
        A turn the engine ended with an error fails; the run stays for the next message.
        """
        session_id = live.session_id
        await isolated("the git audit", session_id, self.audit(live))
        run = live.run
        if run is not None:
            await isolated("the context report", session_id, self._report_context(session_id, run))
        if live.interrupted:
            await self._conclude(live, SessionState.INTERRUPTED, None)
        elif error is not None:
            await self._conclude(live, SessionState.FAILED, error)
        else:
            await self._conclude(live, SessionState.IDLE, None)
        if run is not None:
            # Nothing waits for it, so it waits beside the reader (I-L).
            live.report(
                isolated(
                    "the connector report", session_id, self._report_connectors(session_id, run)
                )
            )

    async def run_stopped(self, live: LiveSession, error: str) -> None:
        # The run already closed itself; the next message opens a new one and resumes.
        live.run = None
        # Its background tasks ended with it; a stale count would keep later runs open.
        live.background_tasks = 0
        if live.turn_active:
            await self._end_turn(live, SessionState.FAILED, error)

    async def background_tasks(self, live: LiveSession, running: int) -> None:
        live.background_tasks = running
        live.schedule_idle_close(self._idle_close)

    async def permission_mode(self, live: LiveSession, mode: PermissionMode) -> None:
        await self._on_mode(live, mode)

    async def checkpoint(self, live: LiveSession, checkpoint_id: str) -> None:
        """Keep the checkpoint of the user message the agent was last given (IMP-02)."""
        event_id, live.user_event = live.user_event, None
        if event_id is not None:
            await self._store.save_checkpoint(live.session_id, event_id, checkpoint_id)

    async def rewind(self, live: LiveSession, checkpoint_id: str, dry_run: bool) -> RewindResult:
        """Restore files to `checkpoint_id` on the session's run, resuming the agent's last
        session when the run was closed; the session counts as busy meanwhile.
        """
        try:
            async with live.hold():
                session = await self._store.get(live.session_id)
                run = await self._ensure_run(live, session, require_cwd(session))
                return await run.rewind_files(checkpoint_id, dry_run)
        finally:
            live.schedule_idle_close(self._idle_close)
            await self.release_held(live)

    async def release_held(self, live: LiveSession) -> None:
        """Start the queue on an idle session when a message waited only for publishing or
        a finishing send (BUG-60, BUG-61); one held by a Stop or a failure keeps waiting.
        """
        if not live.held or live.busy or live.publishing or live.stopped:
            return
        # Starting clears `held`; any turn's end clears it too.
        if await self._has_queued(live) and not live.busy and not live.publishing:
            live.start(lambda: self.guard(live, self._deliver(live, None, None)))

    async def _conclude(self, live: LiveSession, state: SessionState, error: str | None) -> None:
        """End the turn in `state`, or go straight on with the next queued message, so the
        session never rests in between: after a turn that ended normally, or one the user
        interrupted to send a message (a nudge) right away (D032, D036). Otherwise the queue
        waits: the user stopped the agent on purpose, or the failure should show.
        """
        resume = state is SessionState.IDLE or (
            state is SessionState.INTERRUPTED and live.resume_queue
        )
        queued = resume and (live.unsent is not None or await self._has_queued(live))
        queued = queued and not live.stopped  # closing: nothing new starts (BUG-53)
        if live.interrupted and state is SessionState.IDLE:
            # Stop was pressed while the queue was read: it was accepted, so it holds (BUG-59).
            state, queued = SessionState.INTERRUPTED, queued and live.resume_queue
        if not queued:
            await self._end_turn(live, state, error)
            return
        # The next turn starts once its message is sent; Stop until then cancels it.
        live.turn_active = False
        live.interrupted = live.resume_queue = False
        previous = live.task
        live.task = asyncio.create_task(
            self.guard(live, self._deliver(live, previous, (state, error)))
        )

    async def _has_queued(self, live: LiveSession) -> bool:
        try:
            return bool(await self._queue.messages(live.session_id))
        except Exception as error:
            # Bookkeeping: the turn still ends (D048).
            logger.warning("reading the queue of session %s failed (%s)", live.session_id, error)
            return False

    async def _deliver(
        self, live: LiveSession, previous: asyncio.Task[None] | None, ended: Outcome | None
    ) -> Outcome | None:
        """Send the next queued message; `ended` is the outcome if none is left by then."""
        if previous is not None:
            # The task that submitted the turn just ended may still be finishing. A Stop
            # meanwhile cancels only this wait, not that task (BUG-64).
            await asyncio.wait({previous})
        unsent, live.unsent = live.unsent, None
        if unsent is not None:
            await self.submit(live, unsent.text, unsent.attachments, unsent.shown)
            return None
        taking = asyncio.ensure_future(self._take(live))
        try:
            taken = await asyncio.shield(taking)
        except asyncio.CancelledError:
            # Stopped as the message comes off the queue: it is shown, like a message
            # sent just before Stop, rather than lost.
            await asyncio.gather(taking, return_exceptions=True)
            raise
        if taken is None:
            return ended  # the user took it off the queue meanwhile
        await self.submit(live, *taken, shown=True)
        return None

    async def _take(self, live: LiveSession) -> tuple[str, list[Attachment]] | None:
        queued = await self._queue.pop(live.session_id)
        if queued is None:
            return None
        ids = [attachment.id for attachment in queued.attachments]
        attachments = await self._attachments.for_session(ids, live.session_id)
        await self._announce(live, queued.text, attachments)
        return queued.text, attachments

    async def _report_context(self, session_id: str, run: AgentRun) -> None:
        """How full the context window is after the turn, for the session's meter."""
        async with asyncio.timeout(CONTROL_TIMEOUT_SECONDS):
            usage = await run.context_usage()
        if usage is None:
            return
        await self._store.update(session_id, context=usage)
        await self._bus.publish(
            types.SESSION_CONTEXT, {"context": usage.model_dump(mode="json")}, session_id
        )

    async def _end_turn(self, live: LiveSession, state: SessionState, error: str | None) -> None:
        # Free the session before announcing the outcome, so a client reacting to the
        # new state can send the next message straight away; it starts once the hooks,
        # which make the turn's review, are done.
        duration = live.turn_ms(self._clock.now())
        live.end_turn(self._idle_close, held=state is SessionState.IDLE)
        live.settled.clear()
        try:
            await self._states.set(live.session_id, state, error, turn={"duration_ms": duration})
        finally:
            live.settled.set()

    async def _report_connectors(self, session_id: str, run: AgentRun) -> None:
        """MCP connections have settled by the end of a turn, unlike at the run's start."""
        servers = await run.connector_statuses()
        await self._hooks.connectors_reported(session_id, servers)

    async def apply_controls(self, live: LiveSession) -> None:
        """Bring the live run to the session's saved model and permission mode. Without a
        run there is nothing to do: a run that is opening applies them once open.
        """
        async with live.controls:
            run = live.run
            if run is not None:
                await _apply_controls(live, run, await self._store.get(live.session_id))

    async def _ensure_run(self, live: LiveSession, session: Session, cwd: Path) -> AgentRun:
        """The live run, or a new one resuming the agent's last session. Controls saved
        while a run opens apply once it is open, so the saved ones always win (D048).
        """
        dirs = await self._attachments.file_dirs(session.id)
        while (run := live.run) is None or not _fits(live, session, dirs):
            await live.close_run()
            git = await self._repos.has_git(session.repo)
            # Following Claude Code's own mode, the run opens without one (IMP-06).
            mode = None if session.follows_claude_code_mode else session.permission_mode
            spec = SessionSpec(
                cwd=cwd,
                permission_mode=mode,
                model=session.model,
                effort=session.effort,
                resume_id=session.provider_session_id,
                extra_dirs=dirs,
                system_prompt_append=HARNESS_PROMPT if git else PLAIN_FOLDER_PROMPT,
            )
            sink = SessionSink(
                live, self._bus, self._store, self, self._hooks, session.provider_session_id
            )
            live.run = await self._provider.open(spec, self._handler_for(live), sink)
            live.run_dirs = dirs
            live.run_effort = session.effort
            live.run_bypass = mode == BYPASS
            live.run_model = session.model
            live.run_mode = mode
            # A new effort or bypass chosen while it opened needs another run.
            session = await self._store.get(session.id)
        await self.apply_controls(live)
        return run

    async def audit(self, live: LiveSession, publishing: bool = False) -> None:
        """Compare refs with the last audit, at the end of each turn (all refs) and right
        before the daemon publishes (only what the publish uses: HEAD, the branch it names
        and that branch; other changes wait for the next turn end). What this one saw is
        the next one's baseline.
        """
        cwd = require_cwd(await self._store.get(live.session_id))
        after = await snapshot_refs(cwd)
        if publishing and live.baseline is not None:
            after = for_publish(live.baseline, after)
        changes = [] if live.baseline is None else changed_refs(live.baseline, after)
        live.baseline = after
        if changes:
            await set_git_violation(self._store, self._bus, live.session_id, True)
            await self._bus.publish(
                types.SESSION_GIT_VIOLATION, {"changes": changes}, live.session_id
            )


def _keep_unsent(live: LiveSession, unsent: Unsent) -> None:
    """A nudge cut the message off (a plain Stop or closing drops it, as it always did)."""
    if live.resume_queue:
        live.unsent = unsent


def _fits(live: LiveSession, session: Session, dirs: tuple[Path, ...]) -> bool:
    """Whether the live run can take the session's next message as it is."""
    # A new attachment folder, a new effort, or bypass for a run that did not open in it
    # needs a new run (D046), but waits while background tasks run: closing would stop
    # them. Until then the agent asks before reading a new folder's files.
    needs_bypass = session.permission_mode == BYPASS and not live.run_bypass
    same = set(dirs) <= set(live.run_dirs) and live.run_effort == session.effort
    return (same and not needs_bypass) or live.background_tasks > 0


async def _apply_controls(live: LiveSession, run: AgentRun, session: Session) -> None:
    if session.model != live.run_model:
        await run.set_model(session.model)
        live.run_model = session.model
    if session.follows_claude_code_mode:
        return  # the engine reports the mode Claude Code's own settings chose
    mode = session.permission_mode
    # A run that did not open in bypass cannot enter it live; the next message reopens
    # it in bypass instead (D046).
    if mode != live.run_mode and (mode != BYPASS or live.run_bypass):
        await run.set_permission_mode(mode)
        live.run_mode = mode
