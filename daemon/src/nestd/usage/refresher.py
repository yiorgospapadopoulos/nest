"""Keeps the usage windows fresh while a client is visible: Claude's with a probe (D031),
Codex's by asking its app-server for the account's rate limits, without a model call (B91).
The schedule asks for the active accounts' windows and every other signed-in Codex
account's; another Claude account is probed only when asked (B98).
"""

import asyncio
import logging
import math
from collections.abc import Awaitable, Callable
from contextlib import suppress
from datetime import datetime, timedelta

from pydantic import JsonValue

from nestd.clock import Clock
from nestd.errors import NestError
from nestd.events.bus import EventBus
from nestd.providers.base import RunAccount, UsageInfo
from nestd.providers.codex_limits import CODEX
from nestd.usage.models import CLAUDE, EngineLimits, UsageLimits, UsageProvider
from nestd.usage.probe import ProbeError, UsageProbe
from nestd.usage.publish import publish_usage
from nestd.usage.store import UsageStore
from nestd.usage.visibility import ClientVisibility

logger = logging.getLogger(__name__)

# How often the schedule is checked; a probe still waits for its interval.
TICK = timedelta(seconds=20)
# The probe's agent process is closed after this long without a probe.
IDLE_CLOSE = timedelta(minutes=10)
# The least time between a refresh the user asks for and the previous probe.
FORCED_SPACING = timedelta(seconds=20)

type Interval = Callable[[], timedelta | None]
# Codex's windows now; None while it is not signed in or could not say.
type CodexUsage = Callable[[], Awaitable[UsageInfo | None]]
# The active Claude account, ready for a probe (B98).
type ActiveAccount = Callable[[], Awaitable[RunAccount]]


class RefreshTooSoonError(NestError):
    status_code = 429

    def __init__(self, retry_after: int) -> None:
        super().__init__(f"usage was refreshed moments ago; try again in {retry_after} s")
        self.retry_after = retry_after

    def payload(self) -> dict[str, JsonValue]:
        return {**super().payload(), "retry_after": self.retry_after}

    def headers(self) -> dict[str, str]:
        return {"Retry-After": str(self.retry_after)}


class ProbeFailedError(NestError):
    status_code = 502

    def __init__(self, engine: str = "Claude") -> None:
        super().__init__(f"{engine} did not report the usage limits; see the daemon log")


class UsageRefresher:
    def __init__(
        self,
        store: UsageStore,
        bus: EventBus,
        clock: Clock,
        probe: UsageProbe,
        visibility: ClientVisibility,
        interval: Interval,
        codex: CodexUsage,
        tick: timedelta = TICK,
        account: ActiveAccount | None = None,
        other_codex: Callable[[], Awaitable[None]] | None = None,
        claude_signed_in: Callable[[], Awaitable[bool]] | None = None,
    ) -> None:
        """`interval` reads the refresh setting each time; None turns the schedule off.
        `account` is the Claude account probes run on (None: Claude Code's own), and
        `other_codex` reads the inactive Codex accounts' windows with the active one's
        (B98). `claude_signed_in` says whether Claude can be probed at all: without a
        login the schedule leaves it quietly (B106).
        """
        self._claude_signed_in = claude_signed_in
        self._account = account
        self._other_codex = other_codex
        self._store = store
        self._bus = bus
        self._clock = clock
        self._probe = probe
        self.visibility = visibility
        self._interval = interval
        self._codex = codex
        self._tick = tick
        self._lock = asyncio.Lock()
        self._wake = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._last_attempt: datetime | None = None
        self._codex_attempt: datetime | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        await self._probe.close()

    def wake(self) -> None:
        """Check the schedule now, for example because a client just became visible."""
        self._wake.set()

    async def tick(self) -> None:
        """For each engine, ask when the refresh is on, a client is visible, and neither an
        ask nor a session's turn brought its windows within the interval. Closes an idle
        probe client.
        """
        now = self._clock.now()
        if self._last_attempt is not None and now - self._last_attempt >= IDLE_CLOSE:
            await self._probe.close()
        interval = self._interval()
        if interval is None or not self.visibility.any_visible():
            return
        if await self._due(CLAUDE, self._last_attempt, now, interval) and await self._claude():
            self._last_attempt = now
            await self._run_probe()
        if await self._due(CODEX, self._codex_attempt, now, interval):
            self._codex_attempt = now
            await self._run_codex()
            if self._other_codex is not None:
                await self._other_codex()

    async def _claude(self) -> bool:
        return self._claude_signed_in is None or await self._claude_signed_in()

    async def refresh(self) -> UsageLimits:
        """An ask the user made for Claude's windows, at most once per FORCED_SPACING."""
        self._last_attempt = self._spaced(self._last_attempt)
        if not await self._run_probe():
            raise ProbeFailedError
        return await self._store.limits()

    async def refresh_engine(self, provider: UsageProvider) -> EngineLimits:
        """An ask the user made for another engine's windows (Codex's), spaced as Claude's
        are but apart from them.
        """
        self._codex_attempt = self._spaced(self._codex_attempt)
        if not await self._run_codex():
            raise ProbeFailedError("Codex")
        return await self._store.engine_limits(provider)

    async def probe(self, account: RunAccount, announce: bool) -> bool:
        """Probe one Claude account, such as one just signed in to (B98); its windows are
        announced as Claude's only when `announce` (the active account's). Whether the
        probe brought new windows.
        """
        return await self._run_probe(account, announce)

    def _spaced(self, last: datetime | None) -> datetime:
        """Now, unless it is within FORCED_SPACING of the engine's last ask."""
        now = self._clock.now()
        if last is not None and now - last < FORCED_SPACING:
            wait = FORCED_SPACING - (now - last)
            raise RefreshTooSoonError(math.ceil(wait.total_seconds()))
        return now

    async def _due(
        self, provider: UsageProvider, attempt: datetime | None, now: datetime, interval: timedelta
    ) -> bool:
        updated = await self._store.limits_updated_at(provider)
        return all(moment is None or now - moment >= interval for moment in (attempt, updated))

    async def _run_codex(self) -> bool:
        """Whether Codex reported its windows; it logs its own failures."""
        info = await self._codex()
        if info is None:
            return False
        await self._store.update_limits(info)
        await publish_usage(self._bus, info)
        return True

    async def _run_probe(self, account: RunAccount | None = None, announce: bool = True) -> bool:
        """Whether the probe brought new windows. Failures are logged, never raised."""
        if account is None and self._account is not None:
            account = await self._account()
        async with self._lock:
            try:
                outcome = await self._probe.run(account)
            except ProbeError as error:
                logger.warning("usage probe failed: %s", error)
                return False
        await self._store.record_probe(outcome.tokens)
        if outcome.limits is None:
            logger.warning("usage probe: Claude reported no usage windows")
            return False
        await self._store.update_limits(outcome.limits, None if account is None else account.id)
        if announce:
            await publish_usage(self._bus, outcome.limits)
        return True

    async def _loop(self) -> None:
        while True:
            with suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), self._tick.total_seconds())
            self._wake.clear()
            try:
                await self.tick()
            except Exception as error:
                logger.warning("usage refresh failed (%s)", type(error).__name__)
