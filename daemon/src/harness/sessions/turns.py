"""A session's background work: setup, turns on the agent run, and the post-turn git audit."""

import asyncio
import logging
from collections.abc import Callable, Coroutine
from datetime import timedelta
from pathlib import Path
from typing import Any

from harness.attachments.store import Attachment, AttachmentStore
from harness.clock import Clock
from harness.config.models import RepoConfig
from harness.events import types
from harness.events.bus import EventBus
from harness.providers.base import AgentProvider, AgentRun, ApprovalHandler, SessionSpec
from harness.sessions.bookkeeping import isolated
from harness.sessions.git_audit import changed_refs, snapshot_refs
from harness.sessions.hooks import SessionHooks
from harness.sessions.live import BYPASS, LiveSession
from harness.sessions.models import QueuedMessage, Session, SessionState
from harness.sessions.queue import MessageQueue
from harness.sessions.rules import attachment_summary, require_cwd, user_input
from harness.sessions.sink import SessionSink
from harness.sessions.states import StateWriter
from harness.sessions.store import SessionStore
from harness.sessions.workspace import prepare_worktree
from harness.worktrees.manager import WorktreeManager

logger = logging.getLogger(__name__)

HARNESS_PROMPT = (
    "You are running inside harness. Do not run git commit, git push, gh pr create or "
    "gh pr merge: harness commits, pushes and opens pull requests after the user approves "
    "your work. Mention MCP servers that need authorization or failed to connect only when "
    "the user asks about them or the task needs one of them."
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
        attachments: AttachmentStore,
        provider: AgentProvider,
        handler_for: Callable[[LiveSession], ApprovalHandler],
        idle_close: timedelta,
        queue: MessageQueue,
        clock: Clock,
    ) -> None:
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
                await self._end_turn(live, *outcome)

    async def start(
        self, live: LiveSession, session: Session, repo: RepoConfig, attachments: list[Attachment]
    ) -> Outcome | None:
        if session.mode == "worktree":
            setup = await prepare_worktree(session, repo, self._worktrees, self._store, self._bus)
            if not setup.ok:
                return SessionState.FAILED, f"setup command failed: {setup.command}"
        return await self.submit(live, session.prompt, attachments)

    async def submit(self, live: LiveSession, text: str, attachments: list[Attachment]) -> None:
        session_id = live.session_id
        await self._attachments.assign([a.id for a in attachments], session_id)
        await self._bus.publish(
            types.SESSION_USER_MESSAGE,
            {"text": text, "attachments": [attachment_summary(a) for a in attachments]},
            session_id,
        )
        session = await self._start_turn(live)
        cwd = require_cwd(session)
        run = await self._ensure_run(live, session, cwd)
        live.baseline = await snapshot_refs(cwd)
        live.turn_active = True
        await run.send(user_input(text, attachments))

    async def agent_active(self, live: LiveSession) -> None:
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

    async def turn_finished(self, live: LiveSession) -> None:
        """Audit and report the turn, then end it or deliver the next queued message.
        The audit and reports are bookkeeping: their failure never keeps the turn open.
        """
        session_id = live.session_id
        await isolated("the git audit", session_id, self._audit(live))
        run = live.run
        if run is not None:
            await isolated("the context report", session_id, self._report_context(session_id, run))
        # An interrupted turn keeps the queue: the user stopped the agent on purpose,
        # unless they did so to send a message (a nudge) right away.
        hold = live.interrupted and not live.resume_queue
        queued = None if hold else await self._queue.pop(live.session_id)
        if queued is None:
            done = SessionState.INTERRUPTED if live.interrupted else SessionState.IDLE
            await self._end_turn(live, done, None)
        else:
            live.interrupted = live.resume_queue = False
            # The next message starts at once, so the session never goes idle in between.
            previous = live.task
            live.task = asyncio.create_task(self.guard(live, self._deliver(live, queued, previous)))
        if run is not None:
            await isolated(
                "the connector report", session_id, self._report_connectors(session_id, run)
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

    async def _deliver(
        self, live: LiveSession, queued: QueuedMessage, previous: asyncio.Task[None] | None
    ) -> None:
        if previous is not None:
            # The task that submitted the turn just ended may still be finishing.
            await asyncio.gather(previous, return_exceptions=True)
        ids = [attachment.id for attachment in queued.attachments]
        attachments = await self._attachments.for_session(ids, live.session_id)
        await self.submit(live, queued.text, attachments)

    async def _report_context(self, session_id: str, run: AgentRun) -> None:
        """How full the context window is after the turn, for the session's meter."""
        usage = await run.context_usage()
        if usage is None:
            return
        await self._store.update(session_id, context=usage)
        await self._bus.publish(
            types.SESSION_CONTEXT, {"context": usage.model_dump(mode="json")}, session_id
        )

    async def _end_turn(self, live: LiveSession, state: SessionState, error: str | None) -> None:
        # Free the session before announcing the outcome, so a client reacting to the
        # new state can send the next message straight away.
        duration = live.turn_ms(self._clock.now())
        live.end_turn(self._idle_close)
        await self._states.set(live.session_id, state, error, turn={"duration_ms": duration})

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
            spec = SessionSpec(
                cwd=cwd,
                permission_mode=session.permission_mode,
                model=session.model,
                effort=session.effort,
                resume_id=session.provider_session_id,
                extra_dirs=dirs,
                system_prompt_append=HARNESS_PROMPT,
            )
            sink = SessionSink(
                live, self._bus, self._store, self, self._hooks, session.provider_session_id
            )
            live.run = await self._provider.open(spec, self._handler_for(live), sink)
            live.run_dirs = dirs
            live.run_effort = session.effort
            live.run_bypass = session.permission_mode == BYPASS
            live.run_model = session.model
            live.run_mode = session.permission_mode
            # A new effort or bypass chosen while it opened needs another run.
            session = await self._store.get(session.id)
        await self.apply_controls(live)
        return run

    async def _audit(self, live: LiveSession) -> None:
        """Compare refs with the turn's start; the end of this turn starts the next one."""
        cwd = require_cwd(await self._store.get(live.session_id))
        after = await snapshot_refs(cwd)
        changes = changed_refs(live.baseline, after)
        live.baseline = after
        if changes:
            await self._store.update(live.session_id, git_violation=True)
            await self._bus.publish(
                types.SESSION_GIT_VIOLATION, {"changes": changes}, live.session_id
            )


def _fits(live: LiveSession, session: Session, dirs: tuple[Path, ...]) -> bool:
    """Whether the live run can take the session's next message as it is."""
    if not set(dirs) <= set(live.run_dirs):
        return False
    # A new effort, or bypass for a run that did not open in it, needs a new run (D046),
    # but waits while background tasks run: closing would stop them.
    needs_bypass = session.permission_mode == BYPASS and not live.run_bypass
    return (live.run_effort == session.effort and not needs_bypass) or live.background_tasks > 0


async def _apply_controls(live: LiveSession, run: AgentRun, session: Session) -> None:
    if session.model != live.run_model:
        await run.set_model(session.model)
        live.run_model = session.model
    mode = session.permission_mode
    # A run that did not open in bypass cannot enter it live; the next message reopens
    # it in bypass instead (D046).
    if mode != live.run_mode and (mode != BYPASS or live.run_bypass):
        await run.set_permission_mode(mode)
        live.run_mode = mode
