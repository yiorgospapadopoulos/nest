"""Keeps the usage windows fresh with a probe while a client is visible (D031)."""

import asyncio
import logging
import math
from collections.abc import Callable
from contextlib import suppress
from datetime import datetime, timedelta

from pydantic import JsonValue

from nestd.clock import Clock
from nestd.errors import NestError
from nestd.events import types
from nestd.events.bus import EventBus
from nestd.usage.models import UsageLimits
from nestd.usage.probe import ProbeError, UsageProbe
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

    def __init__(self) -> None:
        super().__init__("Claude did not report the usage limits; see the daemon log")


class UsageRefresher:
    def __init__(
        self,
        store: UsageStore,
        bus: EventBus,
        clock: Clock,
        probe: UsageProbe,
        visibility: ClientVisibility,
        interval: Interval,
        tick: timedelta = TICK,
    ) -> None:
        """`interval` reads the refresh setting each time; None turns the schedule off."""
        self._store = store
        self._bus = bus
        self._clock = clock
        self._probe = probe
        self.visibility = visibility
        self._interval = interval
        self._tick = tick
        self._lock = asyncio.Lock()
        self._wake = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._last_attempt: datetime | None = None

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
        """Probe when the refresh is on, a client is visible, and neither a probe nor a
        session's turn brought the windows within the interval. Closes an idle probe client.
        """
        updated = await self._store.limits_updated_at()
        now = self._clock.now()
        if self._last_attempt is not None and now - self._last_attempt >= IDLE_CLOSE:
            await self._probe.close()
        interval = self._interval()
        if interval is None or not self.visibility.any_visible():
            return
        if any(
            moment is not None and now - moment < interval
            for moment in (
                self._last_attempt,
                updated,
            )
        ):
            return
        self._last_attempt = now
        await self._run_probe()

    async def refresh(self) -> UsageLimits:
        """A probe the user asked for, at most once per FORCED_SPACING."""
        now = self._clock.now()
        if self._last_attempt is not None and now - self._last_attempt < FORCED_SPACING:
            wait = FORCED_SPACING - (now - self._last_attempt)
            raise RefreshTooSoonError(math.ceil(wait.total_seconds()))
        self._last_attempt = now
        if not await self._run_probe():
            raise ProbeFailedError
        return await self._store.limits()

    async def _run_probe(self) -> bool:
        """Whether the probe brought new windows. Failures are logged, never raised."""
        async with self._lock:
            try:
                outcome = await self._probe.run()
            except ProbeError as error:
                logger.warning("usage probe failed: %s", error)
                return False
        await self._store.record_probe(outcome.tokens)
        if outcome.limits is None:
            logger.warning("usage probe: Claude reported no usage windows")
            return False
        await self._store.update_limits(outcome.limits)
        await self._bus.publish(types.USAGE_UPDATED, outcome.limits.model_dump(mode="json"))
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
