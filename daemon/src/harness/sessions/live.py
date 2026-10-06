"""What this daemon process holds for a session: its agent run, turn and background tasks."""

import asyncio
import logging
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any

from harness.providers.base import AgentRun
from harness.sessions.errors import SessionBusyError

logger = logging.getLogger(__name__)


@dataclass(eq=False)
class LiveSession:
    session_id: str
    run: AgentRun | None = None
    # Extra directories the run was opened with; new ones need a fresh run.
    run_dirs: tuple[Path, ...] = ()
    # Setup, opening the run and submitting a message. At most one at a time.
    task: asyncio.Task[None] | None = None
    # The agent is working, after a user message or on its own, until the turn's result.
    turn_active: bool = False
    interrupted: bool = False
    # Background tasks the agent reports running; the run is kept open while there are any.
    background_tasks: int = 0
    # Refs at the start of the current turn, for the post-turn audit (D013 layer 4).
    baseline: dict[str, str] = field(default_factory=dict[str, str])
    idle_task: asyncio.Task[None] | None = None

    @property
    def busy(self) -> bool:
        return self.task is not None or self.turn_active

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

    def end_turn(self, idle_close: timedelta) -> None:
        self.turn_active = False
        self.interrupted = False
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
        run, self.run = self.run, None
        if run is None:
            return
        try:
            await run.close()
        except Exception:
            logger.exception("closing the agent run of session %s failed", self.session_id)

    async def stop(self) -> None:
        """Cancel the current task, then close the run and wait for the agent to exit."""
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
