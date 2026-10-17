"""Warns when a usage window reaches `[usage] warn_percent` (D104).

It follows `usage.updated` events, whoever reported the windows (a turn or the probe), and
publishes `usage.warning` the first time a window is at or over the level in its period,
plus a phone notification when `warn_notify` is on. A period is told apart by its reset
time; reports of one period may differ by seconds, so times within an hour are the same.
The warnings already published are read back from the events, so a restart does not
repeat them.
"""

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from contextlib import aclosing, suppress
from datetime import datetime, timedelta

from pydantic import JsonValue, ValidationError

from nestd.config.models import UsageSettings
from nestd.events import types
from nestd.events.bus import EventBus, SubscriptionOverflowError
from nestd.notifications.messages import Notice, usage_warning_notice
from nestd.providers.base import UsageInfo
from nestd.storage.db import Database

logger = logging.getLogger(__name__)

SAME_PERIOD = timedelta(hours=1)

type Push = Callable[[Notice], Awaitable[None]]


class UsageWarnings:
    def __init__(
        self,
        *,
        bus: EventBus,
        db: Database,
        settings: Callable[[], UsageSettings],
        push: Push,
    ) -> None:
        """`settings` is read at each report; `push` sends a notice to the phone."""
        self._bus = bus
        self._db = db
        self._settings = settings
        self._push = push
        # The reset time of the period each window was last warned about.
        self._warned: dict[str, datetime | None] | None = None
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        after = await self._bus.last_id()
        self._task = asyncio.create_task(self._follow(after))

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    async def check(self, info: UsageInfo) -> None:
        settings = self._settings()
        if settings.warn_percent is None:
            return
        level = settings.warn_percent / 100
        warned = await self._load()
        for name, window in (("five_hour", info.five_hour), ("seven_day", info.seven_day)):
            if window is None or window.utilization < level:
                continue
            if name in warned and _same_period(warned[name], window.resets_at):
                continue
            warned[name] = window.resets_at
            payload: dict[str, JsonValue] = {
                "window": name,
                "utilization": window.utilization,
                "resets_at": None if window.resets_at is None else window.resets_at.isoformat(),
            }
            await self._bus.publish(types.USAGE_WARNING, payload)
            if settings.warn_notify:
                await self._push(usage_warning_notice(name, window.utilization))

    async def _load(self) -> dict[str, datetime | None]:
        if self._warned is None:
            rows = await self._db.fetch_all(
                "SELECT payload FROM events WHERE type = ? ORDER BY id", (types.USAGE_WARNING,)
            )
            warned: dict[str, datetime | None] = {}
            for row in rows:
                payload = json.loads(row["payload"])
                resets_at = payload["resets_at"]
                warned[payload["window"]] = (
                    None if resets_at is None else datetime.fromisoformat(resets_at)
                )
            self._warned = warned
        return self._warned

    async def _follow(self, after: int) -> None:
        while True:
            try:
                async with aclosing(self._bus.subscribe(after)) as events:
                    while True:
                        event = await anext(events)
                        after = event.id if event.id is not None else after
                        if event.type == types.USAGE_UPDATED:
                            await self._guarded(event.payload)
            except SubscriptionOverflowError:
                continue

    async def _guarded(self, payload: dict[str, JsonValue]) -> None:
        try:
            await self.check(UsageInfo.model_validate(payload))
        except ValidationError:
            return
        except Exception as error:
            logger.warning("usage warning failed (%s)", type(error).__name__)


def _same_period(warned: datetime | None, resets_at: datetime | None) -> bool:
    if warned is None or resets_at is None:
        return warned is resets_at
    return abs(resets_at - warned) < SAME_PERIOD
