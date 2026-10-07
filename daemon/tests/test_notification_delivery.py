import asyncio
import logging
from collections.abc import AsyncGenerator, AsyncIterator, Callable
from datetime import UTC

import pytest
from pydantic import JsonValue

from harness.config.models import NotificationKinds, NotificationSettings, NtfySettings, QuietHours
from harness.errors import ConflictError
from harness.events import types
from harness.events.bus import EventBus, SubscriptionOverflowError
from harness.events.models import Event
from harness.notifications.delivery import NotificationDelivery
from harness.notifications.messages import TEST_NOTICE
from harness.notifications.subscriptions import PushSubscriptionStore
from harness.notifications.vapid import VapidKeys
from harness.notifications.webpush import PushReport
from harness.storage.db import Database
from tests.fakes import FakeClock, FakeSecretStore
from tests.push_support import FakeServers, Receiver, json_body
from tests.test_push_subscriptions import paired

PHONE = "https://web.push.apple.com/phone"
NTFY = "https://ntfy.sh/"


class Rules:
    """Settings the test can change while the delivery runs."""

    def __init__(self) -> None:
        self.current = NotificationSettings()

    def __call__(self) -> NotificationSettings:
        return self.current


class FlakyBus(EventBus):
    """Overflows the first subscription, as if the delivery had fallen behind."""

    def __init__(self, db: Database, clock: FakeClock) -> None:
        super().__init__(db, clock)
        self.afters: list[int | None] = []

    async def subscribe(self, after_id: int | None = None) -> AsyncGenerator[Event]:
        self.afters.append(after_id)
        if len(self.afters) == 1:
            raise SubscriptionOverflowError("fell behind")
        async for event in super().subscribe(after_id):
            yield event


async def eventually(condition: Callable[[], bool]) -> None:
    for _ in range(500):
        if condition():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition never became true")


class Harness:
    def __init__(self, db: Database, clock: FakeClock, bus: EventBus | None = None) -> None:
        self.db = db
        self.clock = clock
        self.bus = bus or EventBus(db, clock)
        self.servers = FakeServers()
        self.rules = Rules()
        self.store = PushSubscriptionStore(db, clock)
        self.receiver = Receiver()
        self.delivery = NotificationDelivery(
            self.bus,
            self.store,
            VapidKeys(FakeSecretStore()),
            clock,
            self.rules,
            transport=self.servers.transport(),
            zone=UTC,
        )

    async def subscribe(self, endpoint: str = PHONE) -> str:
        device = await paired(self.db, self.clock)
        await self.store.upsert(device, endpoint, self.receiver.p256dh, self.receiver.auth)
        return device

    async def notify(self, kind: str = "needs_approval", session: str = "s1") -> None:
        await self.bus.publish(
            types.NOTIFY,
            {
                "kind": kind,
                "session_id": session,
                "repo": "harness",
                "title": "Fix login",
                "text": "Approve Bash",
            },
            session,
        )

    def pushed(self) -> list[dict[str, JsonValue]]:
        return [self.receiver.read(r.content) for r in self.servers.to(PHONE)]


@pytest.fixture
async def h(db: Database, clock: FakeClock) -> AsyncIterator[Harness]:
    harness = Harness(db, clock)
    yield harness
    await harness.delivery.close()


async def test_notify_events_are_pushed_to_every_active_subscription(h: Harness) -> None:
    await h.subscribe()
    await h.notify("question", "s9")  # before start: not delivered
    await h.delivery.start()

    await h.notify()

    await eventually(lambda: len(h.servers.requests) == 1)
    assert h.pushed() == [
        {
            "title": "Needs approval · harness",
            "body": "Fix login: Approve Bash",
            "url": "/inbox",
            "tag": "session-s1",
        }
    ]


async def test_disabled_kinds_and_other_events_are_not_sent(h: Harness) -> None:
    await h.subscribe()
    h.rules.current = NotificationSettings(kinds=NotificationKinds(finished=False))
    await h.delivery.start()

    await h.notify("finished", "quiet")
    await h.bus.publish(types.NOTIFY, {"kind": "bogus"})
    await h.bus.publish(types.SESSION_STATE, {"state": "idle"}, "s1")
    await h.bus.publish_ephemeral(types.SESSION_DELTA, {"text": "x"}, "s1")
    await h.notify("failed", "loud")

    await eventually(lambda: len(h.servers.requests) == 1)
    await asyncio.sleep(0.05)
    assert [p["tag"] for p in h.pushed()] == ["session-loud"]


def notify_payload(kind: str) -> dict[str, JsonValue]:
    return {"kind": kind, "session_id": "s1", "repo": "harness", "title": "T", "text": "x"}


async def test_quiet_hours_hold_everything_back(h: Harness) -> None:
    await h.subscribe()
    # The fake clock reads 12:00 UTC.
    h.rules.current = NotificationSettings(quiet_hours=QuietHours(start="11:30", end="12:30"))

    await h.delivery.deliver(notify_payload("needs_approval"))
    assert h.servers.requests == []

    h.rules.current = NotificationSettings(quiet_hours=QuietHours(start="12:30", end="11:30"))
    await h.delivery.deliver(notify_payload("needs_approval"))
    assert len(h.servers.requests) == 1


async def test_ntfy_receives_the_same_notice_when_enabled(h: Harness) -> None:
    h.rules.current = NotificationSettings(ntfy=NtfySettings(enabled=True, topic="t0p1c"))
    await h.delivery.start()

    await h.notify()

    await eventually(lambda: len(h.servers.to(NTFY)) == 1)
    assert json_body(h.servers.to(NTFY)[0])["topic"] == "t0p1c"


async def test_a_failing_delivery_is_logged_and_the_next_one_still_goes_out(
    h: Harness, caplog: pytest.LogCaptureFixture
) -> None:
    await h.subscribe()
    await h.delivery.start()
    working = h.rules.current

    def broken() -> NotificationSettings:
        h.rules.current = working
        raise RuntimeError("settings exploded")

    h.delivery._settings = broken  # pyright: ignore[reportPrivateUsage]
    with caplog.at_level(logging.ERROR):
        await h.notify()
        await eventually(lambda: "Notification delivery failed" in caplog.text)
    h.delivery._settings = h.rules  # pyright: ignore[reportPrivateUsage]
    await h.notify("failed")

    await eventually(lambda: len(h.servers.requests) == 1)


async def test_falling_behind_resubscribes_from_the_last_seen_event(
    db: Database, clock: FakeClock
) -> None:
    bus = FlakyBus(db, clock)
    h = Harness(db, clock, bus)
    await h.subscribe()
    start = await bus.last_id()
    try:
        await h.delivery.start()
        await h.notify()
        await eventually(lambda: len(h.servers.requests) == 1)
    finally:
        await h.delivery.close()

    assert bus.afters == [start, start]


async def test_stop_cancels_sends_in_flight(h: Harness) -> None:
    await h.subscribe()
    gate = asyncio.Event()
    original = h.store.active

    async def slow_active() -> list[object]:
        gate.set()
        await asyncio.sleep(3600)
        return list(await original())

    h.store.active = slow_active  # pyright: ignore[reportAttributeAccessIssue]
    await h.delivery.start()
    await h.notify()
    await asyncio.wait_for(gate.wait(), 5)

    await h.delivery.stop()
    await h.delivery.stop()

    assert h.servers.requests == []


async def test_send_test_reaches_only_the_callers_subscriptions(h: Harness) -> None:
    h.rules.current = NotificationSettings(
        kinds=NotificationKinds(needs_approval=False),
        quiet_hours=QuietHours(start="00:00", end="23:59"),
    )
    phone = await h.subscribe()
    await h.subscribe("https://fcm.googleapis.com/other")

    assert await h.delivery.send_test(phone) == PushReport(sent=1)
    assert h.pushed() == [TEST_NOTICE.web_payload()]
    assert h.servers.to("https://fcm.googleapis.com/other") == []


async def test_send_test_without_a_subscription_is_a_conflict(h: Harness) -> None:
    device = await paired(h.db, h.clock)

    with pytest.raises(ConflictError, match="enable notifications"):
        await h.delivery.send_test(device)
