"""Archives Nest chats left idle for the days set in `[storage] archive_after_days` (D104).

It checks when the daemon starts, every hour and when the setting is saved. Pinned chats,
chats in a turn or waiting on the user, and chats paused at the usage limit are kept. Each
archive goes through the same path as the user's Archive, so it is announced the same way.
"""

import asyncio
import logging
from collections.abc import Callable
from contextlib import suppress
from datetime import timedelta

from nestd.clock import Clock
from nestd.config.models import StorageSettings
from nestd.sessions.manager import SessionManager
from nestd.sessions.models import IN_FLIGHT, UpdateSession

logger = logging.getLogger(__name__)

INTERVAL = timedelta(hours=1)


class ChatArchiver:
    def __init__(
        self,
        *,
        sessions: SessionManager,
        clock: Clock,
        settings: Callable[[], StorageSettings],
        interval: timedelta = INTERVAL,
    ) -> None:
        """`settings` is read at each check, so a new limit applies at once."""
        self._sessions = sessions
        self._clock = clock
        self._settings = settings
        self._interval = interval
        self._wake = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    def wake(self) -> None:
        """Check now, as after the setting changed."""
        self._wake.set()

    async def run_once(self) -> list[str]:
        """Archive the chats past the limit; returns their ids."""
        days = self._settings().archive_after_days
        if days is None:
            return []
        cutoff = self._clock.now() - timedelta(days=days)
        archived: list[str] = []
        for session in await self._sessions.list_sessions():
            if (
                session.pinned
                or session.state in IN_FLIGHT
                or session.limit_pause is not None
                or session.updated_at > cutoff
            ):
                continue
            await self._sessions.update(session.id, UpdateSession(archived=True))
            archived.append(session.id)
        return archived

    async def _loop(self) -> None:
        while True:
            try:
                await self.run_once()
            except Exception as error:
                logger.warning("chat archive check failed (%s)", type(error).__name__)
            with suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), self._interval.total_seconds())
            self._wake.clear()
