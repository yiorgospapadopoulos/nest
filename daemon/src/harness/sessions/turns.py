"""A session's background work: setup, turns on the agent run, and the post-turn git audit."""

import logging
from collections.abc import Callable, Coroutine
from datetime import timedelta
from pathlib import Path
from typing import Any

from harness.attachments.store import Attachment, AttachmentStore
from harness.config.models import RepoConfig
from harness.events import types
from harness.events.bus import EventBus
from harness.providers.base import AgentProvider, AgentRun, ApprovalHandler, SessionSpec
from harness.sessions.git_audit import changed_refs, snapshot_refs
from harness.sessions.hooks import SessionHooks
from harness.sessions.live import LiveSession
from harness.sessions.models import Session, SessionState
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
    "your work."
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
        handler_for: Callable[[str], ApprovalHandler],
        idle_close: timedelta,
    ) -> None:
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
        session = await self._states.set(session_id, SessionState.RUNNING)
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
        await self._states.set(live.session_id, SessionState.RUNNING)

    async def turn_finished(self, live: LiveSession) -> None:
        await self._audit(live)
        run = live.run
        done = SessionState.INTERRUPTED if live.interrupted else SessionState.IDLE
        await self._end_turn(live, done, None)
        if run is not None:
            await self._report_connectors(live.session_id, run)

    async def run_stopped(self, live: LiveSession, error: str) -> None:
        # The run already closed itself; the next message opens a new one and resumes.
        live.run = None
        if live.turn_active:
            await self._end_turn(live, SessionState.FAILED, error)

    async def background_tasks(self, live: LiveSession, running: int) -> None:
        live.background_tasks = running
        live.schedule_idle_close(self._idle_close)

    async def _end_turn(self, live: LiveSession, state: SessionState, error: str | None) -> None:
        # Free the session before announcing the outcome, so a client reacting to the
        # new state can send the next message straight away.
        live.end_turn(self._idle_close)
        await self._states.set(live.session_id, state, error)

    async def _report_connectors(self, session_id: str, run: AgentRun) -> None:
        """MCP connections have settled by the end of a turn, unlike at the run's start."""
        try:
            servers = await run.connector_statuses()
        except Exception:
            logger.warning(
                "reading the connector status of session %s failed", session_id, exc_info=True
            )
            return
        await self._hooks.connectors_reported(session_id, servers)

    async def _ensure_run(self, live: LiveSession, session: Session, cwd: Path) -> AgentRun:
        """The live run, or a new one resuming the agent's last session."""
        dirs = await self._attachments.file_dirs(session.id)
        if live.run is not None and set(dirs) <= set(live.run_dirs):
            return live.run
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
        live.run = await self._provider.open(spec, self._handler_for(session.id), sink)
        live.run_dirs = dirs
        return live.run

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
