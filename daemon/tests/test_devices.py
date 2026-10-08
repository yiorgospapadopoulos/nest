import asyncio
import hashlib
import re
from datetime import timedelta

import pytest

from harness.auth.devices import (
    LOCAL_DEVICE_ACCOUNT,
    LOCAL_DEVICE_NAME,
    DeviceService,
    InvalidPairingCodeError,
    PairingLockedError,
)
from harness.storage.db import Database
from tests.fakes import FakeClock, FakeSecretStore


@pytest.fixture
def service(db: Database, clock: FakeClock, secrets: FakeSecretStore) -> DeviceService:
    return DeviceService(db, clock, secrets)


async def test_first_run_creates_the_local_device(
    service: DeviceService, secrets: FakeSecretStore, db: Database
) -> None:
    token = await service.ensure_local_device()

    assert secrets.get(LOCAL_DEVICE_ACCOUNT) == token
    assert len(token) >= 40
    devices = await service.list_devices()
    assert [(d.name, d.is_local) for d in devices] == [(LOCAL_DEVICE_NAME, True)]
    stored = await db.fetch_all("SELECT token_hash FROM devices")
    assert stored[0]["token_hash"] == hashlib.sha256(token.encode()).hexdigest()
    assert token not in str([tuple(row) for row in await db.fetch_all("SELECT * FROM devices")])


async def test_existing_valid_local_token_is_reused(service: DeviceService) -> None:
    token = await service.ensure_local_device()

    assert await service.ensure_local_device() == token
    assert len(await service.list_devices()) == 1


async def test_missing_local_token_is_rotated(
    service: DeviceService, secrets: FakeSecretStore
) -> None:
    old = await service.ensure_local_device()
    del secrets.values[LOCAL_DEVICE_ACCOUNT]  # the Keychain item went missing

    new = await service.ensure_local_device()

    assert new != old
    assert secrets.get(LOCAL_DEVICE_ACCOUNT) == new
    assert await service.authenticate(old) is None
    assert await service.authenticate(new) is not None
    assert len(await service.list_devices()) == 1


async def test_stale_local_token_is_rotated(
    service: DeviceService, secrets: FakeSecretStore
) -> None:
    await service.ensure_local_device()
    secrets.set(LOCAL_DEVICE_ACCOUNT, "not-the-right-token")

    new = await service.ensure_local_device()

    assert new != "not-the-right-token"
    assert await service.authenticate(new) is not None


async def test_revoked_local_device_is_restored_with_a_new_token(
    service: DeviceService,
) -> None:
    old = await service.ensure_local_device()
    (local,) = await service.list_devices()
    assert await service.revoke(local.id)

    new = await service.ensure_local_device()

    assert new != old
    assert await service.authenticate(old) is None
    device = await service.authenticate(new)
    assert device is not None
    assert device.id == local.id


async def test_pairing_code_shape_and_expiry(service: DeviceService, clock: FakeClock) -> None:
    code = await service.create_pairing_code()

    assert re.fullmatch(r"[ABCDEFGHJKMNPQRSTUVWXYZ23456789]{8}", code.code)
    assert code.expires_at == clock.current + timedelta(minutes=5)


async def test_redeeming_a_code_creates_an_authenticating_device(
    service: DeviceService, clock: FakeClock
) -> None:
    code = await service.create_pairing_code()

    device, token = await service.redeem_pairing_code(f" {code.code.lower()} ", "iPhone")

    assert device.name == "iPhone"
    assert device.is_local is False
    assert device.created_at == clock.current
    assert device.last_seen_at is None
    clock.advance(timedelta(minutes=1))
    authenticated = await service.authenticate(token)
    assert authenticated is not None
    assert authenticated.id == device.id
    assert authenticated.last_seen_at == clock.current
    assert [d.id for d in await service.list_devices()] == [device.id]


async def test_codes_are_single_use(service: DeviceService) -> None:
    code = await service.create_pairing_code()
    await service.redeem_pairing_code(code.code, "one")

    with pytest.raises(InvalidPairingCodeError):
        await service.redeem_pairing_code(code.code, "two")


async def test_expired_codes_are_rejected(service: DeviceService, clock: FakeClock) -> None:
    code = await service.create_pairing_code(ttl=timedelta(minutes=1))
    clock.advance(timedelta(minutes=1))

    with pytest.raises(InvalidPairingCodeError):
        await service.redeem_pairing_code(code.code, "late")


async def test_wrong_codes_are_rejected(service: DeviceService) -> None:
    await service.create_pairing_code()

    with pytest.raises(InvalidPairingCodeError):
        await service.redeem_pairing_code("WRONGONE", "guess")


async def test_five_failures_lock_out_redemption_until_the_window_passes(
    service: DeviceService, clock: FakeClock
) -> None:
    code = await service.create_pairing_code(ttl=timedelta(minutes=30))
    for _ in range(4):
        with pytest.raises(InvalidPairingCodeError):
            await service.redeem_pairing_code("WRONGONE", "guess")
        clock.advance(timedelta(seconds=30))
    with pytest.raises(InvalidPairingCodeError):
        await service.redeem_pairing_code("WRONGONE", "guess")

    with pytest.raises(PairingLockedError) as locked:
        await service.redeem_pairing_code(code.code, "owner")
    assert locked.value.retry_after == timedelta(minutes=3)

    # The first failure (two minutes ago) leaves the five-minute window in three minutes.
    clock.advance(timedelta(minutes=3) - timedelta(seconds=1))
    with pytest.raises(PairingLockedError):
        await service.redeem_pairing_code(code.code, "owner")
    clock.advance(timedelta(seconds=1))
    device, _ = await service.redeem_pairing_code(code.code, "owner")
    assert device.name == "owner"


async def test_concurrent_wrong_codes_cannot_slip_past_the_lockout(
    service: DeviceService,
) -> None:
    """D051: every redemption counts before the next one is checked."""
    code = await service.create_pairing_code()

    results = await asyncio.gather(
        *(service.redeem_pairing_code("WRONGONE", "guess") for _ in range(50)),
        return_exceptions=True,
    )

    invalid = [r for r in results if isinstance(r, InvalidPairingCodeError)]
    locked = [r for r in results if isinstance(r, PairingLockedError)]
    assert (len(invalid), len(locked)) == (5, 45)
    with pytest.raises(PairingLockedError):
        await service.redeem_pairing_code(code.code, "owner")


async def test_failures_outside_the_window_do_not_lock(
    service: DeviceService, clock: FakeClock
) -> None:
    code = await service.create_pairing_code(ttl=timedelta(hours=1))
    for _ in range(10):
        with pytest.raises(InvalidPairingCodeError):
            await service.redeem_pairing_code("WRONGONE", "guess")
        clock.advance(timedelta(minutes=2))

    device, _ = await service.redeem_pairing_code(code.code, "owner")

    assert device.name == "owner"


async def test_unknown_and_revoked_tokens_do_not_authenticate(service: DeviceService) -> None:
    code = await service.create_pairing_code()
    device, token = await service.redeem_pairing_code(code.code, "phone")

    assert await service.authenticate("nonsense") is None
    assert await service.revoke(device.id) is True
    assert await service.authenticate(token) is None
    assert await service.list_devices() == []


async def test_revoking_unknown_or_revoked_devices_reports_false(service: DeviceService) -> None:
    code = await service.create_pairing_code()
    device, _ = await service.redeem_pairing_code(code.code, "phone")
    await service.revoke(device.id)

    assert await service.revoke(device.id) is False
    assert await service.revoke("missing") is False


async def test_devices_are_listed_in_creation_order(
    service: DeviceService, clock: FakeClock
) -> None:
    await service.ensure_local_device()
    clock.advance(timedelta(seconds=1))
    code = await service.create_pairing_code()
    await service.redeem_pairing_code(code.code, "phone")

    assert [d.name for d in await service.list_devices()] == [LOCAL_DEVICE_NAME, "phone"]
