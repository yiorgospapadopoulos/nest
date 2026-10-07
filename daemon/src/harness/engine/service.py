"""Keeps Claude Code's model list and account at hand for clients (D038).

A short-lived engine process is asked on start and every six hours; every agent run reports
the same details when it opens, which also counts as a refresh.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import suppress
from datetime import datetime, timedelta
from pathlib import Path

from harness.clock import Clock
from harness.engine.fetch import FetchError
from harness.engine.models import FALLBACK_MODELS, ModelList
from harness.engine.profile import profile_name
from harness.engine.store import EngineInfoStore
from harness.errors import InvalidInputError
from harness.providers.base import AccountInfo, EngineDetails, ModelOption

logger = logging.getLogger(__name__)

# The daemon serves first; then the engine is asked.
START_DELAY = timedelta(seconds=2)
INTERVAL = timedelta(hours=6)
# After a failed fetch, the next attempt waits this long.
RETRY = timedelta(minutes=30)
TICK = timedelta(minutes=5)
# The model a session without a model uses.
DEFAULT_MODEL = "default"


def effort_problem(model: ModelOption, effort: str | None) -> str | None:
    """Why `effort` does not fit `model`; None when it does (no effort always fits)."""
    if effort is None or effort in model.effort_levels:
        return None
    if not model.effort_levels:
        return f"{model.display_name} does not take a thinking level"
    return f"{model.display_name} takes these thinking levels: {', '.join(model.effort_levels)}"


class EngineInfo:
    def __init__(
        self,
        store: EngineInfoStore,
        fetch: Callable[[], Awaitable[EngineDetails]],
        clock: Clock,
        start_delay: timedelta = START_DELAY,
        interval: timedelta = INTERVAL,
        retry: timedelta = RETRY,
        tick: timedelta = TICK,
        account_file: Path | None = None,
    ) -> None:
        """`account_file` is Claude Code's `~/.claude.json`, for the account name (D039);
        None reads no file.
        """
        self._store = store
        self._fetch = fetch
        self._clock = clock
        self._start_delay = start_delay
        self._interval = interval
        self._retry = retry
        self._tick = tick
        self._account_file = account_file
        self._lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None
        self._last_attempt: datetime | None = None
        self._last_report: datetime | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    async def models(self) -> ModelList:
        """The engine's last reported list, or Claude Code's aliases before any report."""
        listed = await self._store.models()
        return listed or ModelList(models=list(FALLBACK_MODELS), updated_at=None)

    async def account(self) -> AccountInfo:
        """The engine's account; without a name from the engine, Claude Code's profile name,
        read on every call so a rename shows at the next refresh.
        """
        account = await self._store.account() or AccountInfo()
        if account.display_name is not None:
            return account
        name = await asyncio.to_thread(profile_name, self._account_file)
        return account.model_copy(update={"display_name": name})

    async def find(self, model: str | None) -> ModelOption | None:
        """The reported entry for `model` (None is Claude Code's default); None when the
        engine has not reported a list or does not list it.
        """
        listed = await self._store.models()
        value = model or DEFAULT_MODEL
        if listed is None:
            return None
        return next((option for option in listed.models if option.value == value), None)

    async def require_effort(self, model: str | None, effort: str | None) -> None:
        """422 when the engine's list knows `model` and it does not take `effort`."""
        option = await self.find(model)
        problem = None if option is None else effort_problem(option, effort)
        if problem is not None:
            raise InvalidInputError(problem)

    async def report(self, details: EngineDetails) -> None:
        """Details an agent run reported when it opened."""
        await self._store.save(details)
        self._last_report = self._clock.now()

    async def refresh(self) -> bool:
        """Ask the engine now; failures are logged with their kind only, never raised."""
        async with self._lock:
            self._last_attempt = self._clock.now()
            try:
                details = await self._fetch()
            except FetchError as error:
                logger.warning("could not read Claude Code's models: %s", error)
                return False
            await self.report(details)
            return True

    async def tick(self) -> None:
        """Fetch when nothing was reported in this process for the interval, and the last
        attempt is at least the retry delay ago.
        """
        now = self._clock.now()
        if self._last_report is not None and now - self._last_report < self._interval:
            return
        if self._last_attempt is not None and now - self._last_attempt < self._retry:
            return
        await self.refresh()

    async def _loop(self) -> None:
        await asyncio.sleep(self._start_delay.total_seconds())
        while True:
            try:
                await self.tick()
            except Exception as error:
                logger.warning("engine info check failed (%s)", type(error).__name__)
            await asyncio.sleep(self._tick.total_seconds())
