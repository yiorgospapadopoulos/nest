"""B103: each device's first visit to Features and the features it has shown."""

import sqlite3
from datetime import timedelta

import pytest

from nestd.auth.devices import DeviceService
from nestd.features.store import FeatureStore
from nestd.storage.db import Database
from tests.fakes import FakeClock, FakeSecretStore


async def paired(db: Database, clock: FakeClock, name: str) -> str:
    devices = DeviceService(db, clock, FakeSecretStore())
    device, _token = await devices.redeem_pairing_code(
        (await devices.create_pairing_code()).code, name, client="phone"
    )
    return device.id


async def test_a_device_that_never_reported_has_no_state(db: Database, clock: FakeClock) -> None:
    phone = await paired(db, clock, "iPhone")

    state = await FeatureStore(db, clock).state(phone)

    assert (state.first_visit, state.shown) == (None, {})


async def test_only_the_first_visit_and_first_showing_are_kept(
    db: Database, clock: FakeClock
) -> None:
    phone = await paired(db, clock, "iPhone")
    store = FeatureStore(db, clock)
    first = clock.now()

    await store.record_shown(phone, ["a", "b", "a"])
    clock.advance(timedelta(hours=3))
    await store.record_shown(phone, ["b", "c"])

    state = await store.state(phone)
    assert state.first_visit == first
    assert state.shown == {"a": first, "b": first, "c": first + timedelta(hours=3)}


async def test_a_report_without_ids_still_records_the_visit(db: Database, clock: FakeClock) -> None:
    phone = await paired(db, clock, "iPhone")
    store = FeatureStore(db, clock)

    await store.record_shown(phone, [])

    state = await store.state(phone)
    assert (state.first_visit, state.shown) == (clock.now(), {})


async def test_each_device_keeps_its_own_state(db: Database, clock: FakeClock) -> None:
    phone = await paired(db, clock, "iPhone")
    ipad = await paired(db, clock, "iPad")
    store = FeatureStore(db, clock)

    await store.record_shown(phone, ["a"])
    clock.advance(timedelta(days=2))
    await store.record_shown(ipad, ["b"])

    assert (await store.state(phone)).shown == {"a": clock.now() - timedelta(days=2)}
    assert (await store.state(ipad)).shown == {"b": clock.now()}
    assert (await store.state(ipad)).first_visit == clock.now()


async def test_an_unknown_device_is_refused(db: Database, clock: FakeClock) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        await FeatureStore(db, clock).record_shown("nobody", ["a"])
