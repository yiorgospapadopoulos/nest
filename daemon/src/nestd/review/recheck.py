"""Check the pending reviews of a project again whenever its branches move (B160), as when
the user commits a chat's work from a terminal: the review watcher hears of the work only
at a turn's end otherwise.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import aclosing

from nestd.events import types
from nestd.events.bus import EventBus, SubscriptionOverflowError
from nestd.repos.service import RepoService

logger = logging.getLogger(__name__)


class ReviewRecheck:
    def __init__(
        self, *, bus: EventBus, repos: RepoService, recheck: Callable[[str], Awaitable[None]]
    ) -> None:
        self._bus = bus
        self._repos = repos
        self._recheck = recheck
        self._due: set[str] = set()
        self._wake = asyncio.Event()
        self._tasks: list[asyncio.Task[None]] = []

    async def start(self) -> None:
        self._tasks = [asyncio.create_task(self._listen()), asyncio.create_task(self._work())]

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []

    async def _listen(self) -> None:
        while True:
            try:
                async with aclosing(self._bus.subscribe()) as events:
                    async for event in events:
                        if event.type == types.REPO_BRANCHES_CHANGED:
                            self._due.add(str(event.payload["name"]))
                            self._wake.set()
            except SubscriptionOverflowError:
                self._due.update(repo.name for repo in self._repos.list_repos())
                self._wake.set()

    async def _work(self) -> None:
        """One project at a time; branches moving again meanwhile checks it once more."""
        while True:
            await self._wake.wait()
            self._wake.clear()
            while self._due:
                name = self._due.pop()
                try:
                    await self._recheck(name)
                except Exception:
                    logger.exception("checking the reviews of %s again failed", name)
