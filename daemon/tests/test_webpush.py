import logging
from collections.abc import AsyncIterator

import httpx
import pytest
from py_vapid import Vapid02

from nestd.notifications.messages import Notice
from nestd.notifications.subscriptions import PushSubscription, PushSubscriptionStore
from nestd.notifications.vapid import VapidKeys
from nestd.notifications.webpush import PushReport, WebPushChannel
from nestd.storage.db import Database
from tests.fakes import START, FakeClock, FakeSecretStore
from tests.push_support import FakeServers, Receiver
from tests.test_push_subscriptions import paired

NOTICE = Notice(
    kind="needs_approval",
    title="Needs approval · nest",
    body="Fix login: Approve Bash",
    url="/inbox",
    tag="session-s1",
    urgent=True,
)
SUBJECT = "mailto:me@example.org"


@pytest.fixture
def servers() -> FakeServers:
    return FakeServers()


@pytest.fixture
async def http(servers: FakeServers) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(transport=servers.transport()) as client:
        yield client


@pytest.fixture
def store(db: Database, clock: FakeClock) -> PushSubscriptionStore:
    return PushSubscriptionStore(db, clock)


@pytest.fixture
def channel(
    store: PushSubscriptionStore, clock: FakeClock, http: httpx.AsyncClient
) -> WebPushChannel:
    return WebPushChannel(store, VapidKeys(FakeSecretStore()), clock, http)


async def subscribe(
    store: PushSubscriptionStore, db: Database, clock: FakeClock, endpoint: str, receiver: Receiver
) -> PushSubscription:
    device = await paired(db, clock)
    return await store.upsert(device, endpoint, receiver.p256dh, receiver.auth)


async def test_sends_an_encrypted_payload_with_vapid_headers(
    channel: WebPushChannel,
    store: PushSubscriptionStore,
    db: Database,
    clock: FakeClock,
    servers: FakeServers,
) -> None:
    receiver = Receiver()
    endpoint = "https://web.push.apple.com/QG/abc"
    sub = await subscribe(store, db, clock, endpoint, receiver)

    report = await channel.send(NOTICE, [sub], SUBJECT)

    assert report == PushReport(sent=1)
    [request] = servers.to(endpoint)
    assert request.method == "POST"
    assert request.headers["content-encoding"] == "aes128gcm"
    assert request.headers["ttl"] == "86400"
    assert request.headers["urgency"] == "high"
    assert Vapid02.verify(request.headers["authorization"])
    assert receiver.read(request.content) == NOTICE.web_payload()
    [after] = await store.for_device(sub.device_id)
    assert after.last_success_at == START


async def test_routine_notices_are_normal_urgency(
    channel: WebPushChannel,
    store: PushSubscriptionStore,
    db: Database,
    clock: FakeClock,
    servers: FakeServers,
) -> None:
    sub = await subscribe(store, db, clock, "https://fcm.googleapis.com/x", Receiver())
    routine = Notice(kind="finished", title="t", body="b", url="/chat/s", tag="t", urgent=False)

    await channel.send(routine, [sub], SUBJECT)

    assert servers.requests[0].headers["urgency"] == "normal"


@pytest.mark.parametrize("status", [404, 410])
async def test_expired_subscriptions_are_deleted(
    channel: WebPushChannel,
    store: PushSubscriptionStore,
    db: Database,
    clock: FakeClock,
    servers: FakeServers,
    status: int,
) -> None:
    endpoint = "https://push.example/gone"
    servers.statuses[endpoint] = status
    sub = await subscribe(store, db, clock, endpoint, Receiver())

    assert await channel.send(NOTICE, [sub], SUBJECT) == PushReport(removed=1)
    assert await store.for_device(sub.device_id) == []


async def test_other_failures_are_counted_and_logged_without_secrets(
    channel: WebPushChannel,
    store: PushSubscriptionStore,
    db: Database,
    clock: FakeClock,
    servers: FakeServers,
    caplog: pytest.LogCaptureFixture,
) -> None:
    rejected = "https://push.example/secret-path-1"
    down = "https://push.example/secret-path-2"
    servers.statuses[rejected] = 403
    servers.broken.add(down)
    receiver = Receiver()
    first = await subscribe(store, db, clock, rejected, receiver)
    second = await subscribe(store, db, clock, down, receiver)

    with caplog.at_level(logging.WARNING):
        report = await channel.send(NOTICE, [first, second], SUBJECT)

    assert report == PushReport(failed=2)
    assert (await store.for_device(first.device_id))[0].failures == 1
    assert (await store.for_device(second.device_id))[0].failures == 1
    assert "push.example" in caplog.text
    assert "403" in caplog.text
    assert "secret-path" not in caplog.text
    assert receiver.auth not in caplog.text


async def test_unusable_keys_count_as_a_failure(
    channel: WebPushChannel, store: PushSubscriptionStore, db: Database, clock: FakeClock
) -> None:
    device = await paired(db, clock)
    sub = await store.upsert(device, "https://push.example/a", "AAAA", "AAAA")

    assert await channel.send(NOTICE, [sub], SUBJECT) == PushReport(failed=1)


async def test_nothing_to_send_to(channel: WebPushChannel) -> None:
    assert await channel.send(NOTICE, [], SUBJECT) == PushReport()
