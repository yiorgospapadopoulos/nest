"""Delivers `notify` events to the phone by web push and, if enabled, ntfy.

It follows the event bus from the moment it starts, applies the user's notification rules
and sends in background tasks, so a slow push service never holds up the daemon.
"""

import asyncio
import logging
from collections.abc import Callable, Coroutine, Mapping
from contextlib import aclosing, suppress
from datetime import time, tzinfo

import httpx
from pydantic import JsonValue

from nestd.clock import Clock
from nestd.config.models import NotificationSettings
from nestd.errors import ConflictError
from nestd.events import types
from nestd.events.bus import EventBus, SubscriptionOverflowError
from nestd.notifications.messages import TEST_NOTICE, Notice, notice_from_event
from nestd.notifications.ntfy import NtfyChannel
from nestd.notifications.rules import in_quiet_hours, should_send
from nestd.notifications.subscriptions import PushSubscriptionStore
from nestd.notifications.vapid import VapidKeys
from nestd.notifications.webpush import PushReport, WebPushChannel

HTTP_TIMEOUT_SECONDS = 15

logger = logging.getLogger(__name__)


class NotificationDelivery:
    def __init__(
        self,
        bus: EventBus,
        subscriptions: PushSubscriptionStore,
        keys: VapidKeys,
        clock: Clock,
        settings: Callable[[], NotificationSettings],
        transport: httpx.AsyncBaseTransport | None = None,
        zone: tzinfo | None = None,
    ) -> None:
        """`settings` returns the rules in force, which the user can change at any time.

        `zone` is where quiet hours are read; None is the system's time zone. `transport`
        replaces the network in tests.
        """
        self.subscriptions = subscriptions
        self.keys = keys
        self._bus = bus
        self._clock = clock
        self._settings = settings
        self._zone = zone
        self._http = httpx.AsyncClient(transport=transport, timeout=HTTP_TIMEOUT_SECONDS)
        self._webpush = WebPushChannel(subscriptions, keys, clock, self._http)
        self._ntfy = NtfyChannel(self._http)
        self._follower: asyncio.Task[None] | None = None
        self._sends: set[asyncio.Task[None]] = set()

    async def start(self) -> None:
        # Everything published from here on is delivered, even before the task first runs.
        after = await self._bus.last_id()
        self._follower = asyncio.create_task(self._follow(after))

    async def stop(self) -> None:
        tasks = [*self._sends, *([self._follower] if self._follower else [])]
        self._follower = None
        for task in tasks:
            task.cancel()
        for task in tasks:
            with suppress(asyncio.CancelledError):
                await task

    async def close(self) -> None:
        await self.stop()
        await self._http.aclose()

    async def send_test(self, device_id: str) -> PushReport:
        """A test notification to one device, regardless of rules and quiet hours."""
        subscriptions = await self.subscriptions.for_device(device_id)
        if not subscriptions:
            msg = "this device has no push subscription; enable notifications first"
            raise ConflictError(msg)
        return await self._webpush.send(TEST_NOTICE, subscriptions, self._settings().vapid_subject)

    async def deliver(self, payload: Mapping[str, JsonValue]) -> None:
        notice = notice_from_event(payload)
        if notice is None:
            return
        settings = self._settings()
        if not should_send(settings, notice.kind, self._local_time()):
            return
        await self._send(notice, settings)

    async def push(self, notice: Notice) -> None:
        """Send a notice that has its own switch, such as a usage warning (D104): the
        kinds do not apply, quiet hours do.
        """
        settings = self._settings()
        if in_quiet_hours(settings.quiet_hours, self._local_time()):
            return
        await self._send(notice, settings)

    def _local_time(self) -> time:
        return self._clock.now().astimezone(self._zone).time()

    async def _send(self, notice: Notice, settings: NotificationSettings) -> None:
        subscriptions = await self.subscriptions.active()
        await asyncio.gather(
            self._webpush.send(notice, subscriptions, settings.vapid_subject),
            self._ntfy.send(notice, settings.ntfy),
        )

    async def _follow(self, after: int) -> None:
        while True:
            try:
                async with aclosing(self._bus.subscribe(after)) as events:
                    while True:
                        event = await anext(events)
                        after = event.id if event.id is not None else after
                        if event.type == types.NOTIFY:
                            self._spawn(self._guarded(self.deliver(event.payload)))
            except SubscriptionOverflowError:
                # Fell behind: subscribe again and replay what was missed.
                continue

    def _spawn(self, work: Coroutine[None, None, None]) -> None:
        task = asyncio.create_task(work)
        self._sends.add(task)
        task.add_done_callback(self._sends.discard)

    async def _guarded(self, work: Coroutine[None, None, None]) -> None:
        try:
            await work
        except Exception:
            logger.exception("Notification delivery failed")
