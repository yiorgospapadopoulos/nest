"""What this daemon process holds for a session: its agent run, turn and background tasks."""

import asyncio
import logging
from collections.abc import AsyncGenerator, Callable, Coroutine
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from nestd.attachments.store import Attachment
from nestd.config.models import Effort, PermissionMode
from nestd.providers.base import AgentRun, LimitHit
from nestd.sessions.errors import SessionBusyError
from nestd.sessions.models import USER, Sender
from nestd.sessions.subagents import NO_AGENTS, ChatAgents

logger = logging.getLogger(__name__)

BYPASS: PermissionMode = "bypassPermissions"


def _set_event() -> asyncio.Event:
    event = asyncio.Event()
    event.set()
    return event


@dataclass(frozen=True)
class Unsent:
    """A message a nudge cut off before the agent got it; `shown` once announced."""

    text: str
    attachments: list[Attachment]
    shown: bool
    sender: Sender = USER


@dataclass(eq=False)
class LiveSession:
    session_id: str
    run: AgentRun | None = None
    # Extra directories the run was opened with; new ones need a fresh run.
    run_dirs: tuple[Path, ...] = ()
    # The thinking effort the run opened with; a different one needs a new run.
    run_effort: Effort | None = None
    # Whether the run opened in bypass: only such a run may switch into it live (D046).
    run_bypass: bool = False
    # The model and permission mode the run has now, to bring it to the saved ones (D048).
    run_model: str | None = None
    run_mode: PermissionMode | None = None
    # The subagents and teams the run opened with; another set needs a new run (B40).
    run_agents: ChatAgents = NO_AGENTS
    # The account the run opened on; once another is active, the next turn opens a new
    # run on it (B98). None without accounts.
    run_account: str | None = None
    # Held while the saved model and mode are read and sent to the run, so the last saved win.
    controls: asyncio.Lock = field(default_factory=asyncio.Lock)
    # Held while the state moves between running and waiting, so two prompts opening at
    # once announce the change once.
    prompts: asyncio.Lock = field(default_factory=asyncio.Lock)
    # Setup, opening the run and submitting a message. At most one at a time.
    task: asyncio.Task[None] | None = None
    # The agent is working, after a user message or on its own, until the turn's result.
    turn_active: bool = False
    # When the agent was given the current turn's message or started one on its own (D045).
    turn_started: datetime | None = None
    interrupted: bool = False
    # The turn was interrupted to deliver a queued message (a nudge) right after it.
    resume_queue: bool = False
    # The message a nudge cut off on its way to the agent; it goes first (BUG-58).
    unsent: Unsent | None = None
    # Set first when the session is closed, archived, deleted or the daemon stops: no new
    # work starts on this live state any more (BUG-53).
    stopped: bool = False
    # The worktree is being created and set up: a nudge waits for it instead of cutting it
    # off, so the prompt never runs without its setup (BUG-95). A Stop still cuts it off.
    preparing: bool = False
    # A message was queued only because publishing or a send still finishing held the
    # session, or as a turn ended normally; the queue starts once that hold ends (BUG-60,
    # BUG-61, BUG-85).
    held: bool = False
    # Background tasks the agent reports running; the run is kept open while there are any.
    background_tasks: int = 0
    # A pixie chat whose context filled up: its next turn opens a fresh run (D072).
    rotate: bool = False
    # The user message event the agent was last given, until the engine echoes it with its
    # file checkpoint id (IMP-02).
    user_event: int | None = None
    # Held while messages are written into the running turn or taken back from it, so a
    # turn's end sees every message the agent has (B59).
    steering: asyncio.Lock = field(default_factory=asyncio.Lock)
    # The turn ended while the agent had read a message written into it but not echoed it
    # yet: the agent starts its next turn with that message, so the turn goes on (B59).
    engine_next: bool = False
    # The turn's end is being concluded: a message sent meanwhile waits in the queue (B59).
    concluding: bool = False
    # The usage limit the engine reported in the current turn, until the turn ends (B78).
    limit_hit: LimitHit | None = None
    idle_task: asyncio.Task[None] | None = None
    # Reports that wait on the run's answer to a control request, off the reader of the
    # agent's messages (I-L); they end with the run.
    reports: set[asyncio.Task[None]] = field(default_factory=set[asyncio.Task[None]])
    # Cleared while a turn's end is announced, which makes its review: a message sent
    # then waits, so its turn starts after that review instead of beside it (BUG-18).
    settled: asyncio.Event = field(default_factory=_set_event)
    # Cleared while the daemon commits, pushes or merges the session's work: messages
    # sent meanwhile are queued and a turn the agent starts on its own waits (BUG-14).
    published: asyncio.Event = field(default_factory=_set_event)
    # Cleared while a closing run's process exits; a new run waits for it (BUG-16).
    run_closed: asyncio.Event = field(default_factory=_set_event)
    # Cleared while `hold` keeps the session busy (restoring files): a turn the agent
    # starts on its own waits, and Stop or a nudge leaves the hold alone (BUG-88, BUG-89).
    unheld: asyncio.Event = field(default_factory=_set_event)

    @property
    def busy(self) -> bool:
        return self.task is not None or self.turn_active

    @property
    def publishing(self) -> bool:
        return not self.published.is_set()

    @property
    def holding(self) -> bool:
        return not self.unheld.is_set()

    @property
    def nudgeable(self) -> bool:
        """Whether a nudge cuts the current work off, rather than waiting for a restore of
        files or the worktree's setup to finish (BUG-88, BUG-95).
        """
        return self.busy and not self.holding and not self.preparing

    def require_idle(self) -> None:
        if self.busy:
            msg = f"session {self.session_id!r} is busy; wait for the turn or interrupt it"
            raise SessionBusyError(msg)

    def start(self, work: Callable[[], Coroutine[Any, Any, None]]) -> None:
        if self.stopped:
            msg = f"session {self.session_id!r} was stopped meanwhile; send the message again"
            raise SessionBusyError(msg)
        self.require_idle()
        self.cancel_idle_close()
        # The queue goes on from here as turns end; a Stop holds it again.
        self.held = False
        self.task = asyncio.create_task(work())

    @asynccontextmanager
    async def hold(self) -> AsyncGenerator[None]:
        """Keep the idle session busy while the caller's own task works on its run, such
        as restoring files: a message sent meanwhile is queued, and a Stop does not cut it
        off. The caller checked that it is idle.
        """
        self.cancel_idle_close()
        task = self.task = asyncio.current_task()
        self.unheld.clear()
        try:
            yield
        finally:
            self.unheld.set()
            if self.task is task:
                self.task = None

    async def interrupt(self) -> bool:
        """Stop the current turn or task; False if nothing is in progress."""
        if self.turn_active and self.run is not None:
            self.interrupted = True
            await self.run.interrupt()
            return True
        if self.task is not None and not self.holding:
            self.interrupted = True
            self.task.cancel()
            return True
        return False

    def turn_ms(self, now: datetime) -> int | None:
        """How long the current turn has run; None if the agent never got its message."""
        if self.turn_started is None:
            return None
        return round((now - self.turn_started).total_seconds() * 1000)

    def end_turn(self, held: bool) -> None:
        """`held` after a turn that ended normally: a message stored only now still starts
        (BUG-85). After a Stop or a failure the queue waits (BUG-61).
        """
        self.turn_active = False
        self.turn_started = None
        self.interrupted = False
        self.resume_queue = False
        self.engine_next = False
        self.held = held

    def schedule_idle_close(self, idle_close: timedelta) -> None:
        """Close an idle run later, but never while the agent has background tasks running."""
        self.cancel_idle_close()
        if self.run is not None and not self.busy and not self.background_tasks:
            self.idle_task = asyncio.create_task(self._close_when_idle(idle_close))

    def cancel_idle_close(self) -> None:
        if self.idle_task is not None:
            self.idle_task.cancel()
            self.idle_task = None

    def report(self, work: Coroutine[Any, Any, None]) -> None:
        """Run `work`, which asks the run something, beside the reader of its messages."""
        task = asyncio.create_task(work)
        self.reports.add(task)
        task.add_done_callback(self.reports.discard)

    async def close_run(self) -> None:
        """Close the run and wait for its process to exit, or for a close in progress."""
        reports, self.reports = self.reports, set[asyncio.Task[None]]()
        for task in reports:
            task.cancel()
        await asyncio.gather(*reports, return_exceptions=True)
        run, self.run = self.run, None
        # Background tasks live in the agent process and end with it.
        self.background_tasks = 0
        if run is None:
            await self.run_closed.wait()
            return
        self.run_closed.clear()
        try:
            await run.close()
        except Exception:
            logger.exception("closing the agent run of session %s failed", self.session_id)
        finally:
            self.run_closed.set()

    async def stop(self) -> None:
        """Cancel the current task, then close the run and wait for the agent to exit."""
        # Stopping for good: no queued message starts after the cancelled task.
        self.stopped = True
        self.resume_queue = False
        self.unsent = None
        task = self.task
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self.cancel_idle_close()
        await self.close_run()

    async def _close_when_idle(self, idle_close: timedelta) -> None:
        await asyncio.sleep(idle_close.total_seconds())
        # Detach first, so a new turn starting now opens a fresh run instead of cancelling this.
        self.idle_task = None
        await self.close_run()
