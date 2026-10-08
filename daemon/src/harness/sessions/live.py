"""What this daemon process holds for a session: its agent run, turn and background tasks."""

import asyncio
import logging
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from harness.config.models import Effort, PermissionMode
from harness.providers.base import AgentRun
from harness.sessions.errors import SessionBusyError

logger = logging.getLogger(__name__)

BYPASS: PermissionMode = "bypassPermissions"


def _set_event() -> asyncio.Event:
    event = asyncio.Event()
    event.set()
    return event


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
    # Background tasks the agent reports running; the run is kept open while there are any.
    background_tasks: int = 0
    # Refs as the last audit saw them, for the next one (D013 layer 4); None before the
    # first turn of this process.
    baseline: dict[str, str] | None = None
    idle_task: asyncio.Task[None] | None = None
    # Cleared while a turn's end is announced, which makes its review: a message sent
    # then waits, so it supersedes that review instead of running beside it (BUG-18).
    settled: asyncio.Event = field(default_factory=_set_event)
    # Cleared while the daemon commits, pushes or merges the session's work: messages
    # sent meanwhile are queued and a turn the agent starts on its own waits (BUG-14).
    published: asyncio.Event = field(default_factory=_set_event)
    # Cleared while a closing run's process exits; a new run waits for it (BUG-16).
    run_closed: asyncio.Event = field(default_factory=_set_event)

    @property
    def busy(self) -> bool:
        return self.task is not None or self.turn_active

    @property
    def publishing(self) -> bool:
        return not self.published.is_set()

    def require_idle(self) -> None:
        if self.busy:
            msg = f"session {self.session_id!r} is busy; wait for the turn or interrupt it"
            raise SessionBusyError(msg)

    def start(self, work: Callable[[], Coroutine[Any, Any, None]]) -> None:
        self.require_idle()
        self.cancel_idle_close()
        self.task = asyncio.create_task(work())

    async def interrupt(self) -> bool:
        """Stop the current turn or task; False if nothing is in progress."""
        if self.turn_active and self.run is not None:
            self.interrupted = True
            await self.run.interrupt()
            return True
        if self.task is not None:
            self.interrupted = True
            self.task.cancel()
            return True
        return False

    def turn_ms(self, now: datetime) -> int | None:
        """How long the current turn has run; None if the agent never got its message."""
        if self.turn_started is None:
            return None
        return round((now - self.turn_started).total_seconds() * 1000)

    def end_turn(self, idle_close: timedelta) -> None:
        self.turn_active = False
        self.turn_started = None
        self.interrupted = False
        self.resume_queue = False
        self.schedule_idle_close(idle_close)

    def schedule_idle_close(self, idle_close: timedelta) -> None:
        """Close an idle run later, but never while the agent has background tasks running."""
        self.cancel_idle_close()
        if self.run is not None and not self.busy and not self.background_tasks:
            self.idle_task = asyncio.create_task(self._close_when_idle(idle_close))

    def cancel_idle_close(self) -> None:
        if self.idle_task is not None:
            self.idle_task.cancel()
            self.idle_task = None

    async def close_run(self) -> None:
        """Close the run and wait for its process to exit, or for a close in progress."""
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
        self.resume_queue = False
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
