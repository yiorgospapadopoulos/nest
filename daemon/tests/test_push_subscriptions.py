from datetime import timedelta

import pytest

from harness.auth.devices import DeviceService
from harness.notifications.subscriptions import PushSubscriptionStore
from harness.storage.db import Database
from tests.fakes import START, FakeClock, FakeSecretStore


@pytest.fixture
def store(db: Database, clock: FakeClock) -> PushSubscriptionStore:
    return PushSubscriptionStore(db, clock)


async def paired(db: Database, clock: FakeClock, name: str = "iPhone") -> str:
    devices = DeviceService(db, clock, FakeSecretStore())
    device, _token = await devices.redeem_pairing_code(
        (await devices.create_pairing_code()).code, name
    )
    return device.id


async def test_subscribe_stores_the_keys_for_the_device(
    store: PushSubscriptionStore, db: Database, clock: FakeClock
) -> None:
    phone = await paired(db, clock)

    sub = await store.upsert(phone, "https://web.push.apple.com/a", "p1", "a1")

    assert sub.device_id == phone
    assert (sub.endpoint, sub.p256dh, sub.auth) == ("https://web.push.apple.com/a", "p1", "a1")
    assert sub.created_at == START
    assert sub.last_success_at is None
    assert sub.failures == 0
    assert await store.for_device(phone) == [sub]


async def test_subscribing_again_updates_keys_and_owner_but_keeps_identity(
    store: PushSubscriptionStore, db: Database, clock: FakeClock
) -> None:
    phone = await paired(db, clock)
    first = await store.upsert(phone, "https://push.example/a", "p1", "a1")
    await store.failed(first.id)
    clock.advance(timedelta(minutes=5))
    again = await paired(db, clock, "iPhone again")

    updated = await store.upsert(again, "https://push.example/a", "p2", "a2")

    assert updated.id == first.id
    assert updated.created_at == START
    assert (updated.device_id, updated.p256dh, updated.auth, updated.failures) == (
        again,
        "p2",
        "a2",
        0,
    )
    assert await store.for_device(phone) == []


async def test_remove_only_deletes_the_callers_own_subscription(
    store: PushSubscriptionStore, db: Database, clock: FakeClock
) -> None:
    phone = await paired(db, clock)
    other = await paired(db, clock, "iPad")
    await store.upsert(phone, "https://push.example/a", "p", "a")

    assert await store.remove(other, "https://push.example/a") is False
    assert await store.remove(phone, "https://push.example/a") is True
    assert await store.remove(phone, "https://push.example/a") is False
    assert await store.for_device(phone) == []


async def test_active_skips_revoked_devices_and_forget_device_deletes(
    store: PushSubscriptionStore, db: Database, clock: FakeClock
) -> None:
    devices = DeviceService(db, clock, FakeSecretStore())
    phone = await paired(db, clock)
    ipad = await paired(db, clock, "iPad")
    a = await store.upsert(phone, "https://push.example/a", "p", "a")
    b = await store.upsert(ipad, "https://push.example/b", "p", "a")
    assert [s.id for s in await store.active()] == [a.id, b.id]

    await devices.revoke(ipad)
    assert [s.id for s in await store.active()] == [a.id]
    assert await store.forget_device(ipad) == 1
    assert await store.for_device(ipad) == []


async def test_delivery_outcomes_are_recorded(
    store: PushSubscriptionStore, db: Database, clock: FakeClock
) -> None:
    phone = await paired(db, clock)
    sub = await store.upsert(phone, "https://push.example/a", "p", "a")

    await store.failed(sub.id)
    await store.failed(sub.id)
    assert (await store.for_device(phone))[0].failures == 2
    clock.advance(timedelta(hours=1))
    await store.succeeded(sub.id)
    [after] = await store.for_device(phone)
    assert (after.failures, after.last_success_at) == (0, START + timedelta(hours=1))

    await store.delete(sub.id)
    assert await store.for_device(phone) == []
