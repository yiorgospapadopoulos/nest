import tomllib
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from pydantic import JsonValue

from nestd.events import types
from nestd.notifications.messages import TEST_NOTICE
from nestd.notifications.vapid import VAPID_ACCOUNT
from tests.api_client import Api, running_api
from tests.fakes import FakeClock, FakeSecretStore
from tests.push_support import FakeServers, Receiver, b64
from tests.test_notification_delivery import eventually

ENDPOINT = "https://web.push.apple.com/QG/device-1"


@pytest.fixture
def servers() -> FakeServers:
    return FakeServers()


@pytest.fixture
async def api(
    tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore, servers: FakeServers
) -> AsyncIterator[Api]:
    async with running_api(tmp_path, clock, secrets, servers.transport()) as running:
        yield running


async def pair_phone(api: Api) -> dict[str, str]:
    code = (await api.http.post("/api/pairing/codes")).json()["code"]
    redeemed = (
        await api.http.post("/api/pairing/redeem", json={"code": code, "device_name": "iPhone"})
    ).json()
    api.http.cookies.clear()
    return {"Authorization": f"Bearer {redeemed['token']}", "X-Device": redeemed["device"]["id"]}


def subscription(receiver: Receiver, endpoint: str = ENDPOINT) -> dict[str, JsonValue]:
    return {"endpoint": endpoint, "expirationTime": None, "keys": receiver.keys()}


async def test_vapid_key_is_created_once_and_kept_in_the_secret_store(
    api: Api, secrets: FakeSecretStore
) -> None:
    first = await api.http.get("/api/push/vapid-key")
    second = await api.http.get("/api/push/vapid-key")

    assert first.status_code == 200
    assert first.json() == second.json()
    assert len(first.json()["public_key"]) == 87
    assert secrets.get(VAPID_ACCOUNT) is not None


async def test_push_routes_need_a_device(api: Api) -> None:
    anonymous = {"Authorization": "Bearer wrong"}
    for method, url in [
        ("GET", "/api/push/vapid-key"),
        ("POST", "/api/push/subscribe"),
        ("DELETE", "/api/push/subscribe"),
        ("POST", "/api/push/test"),
        ("GET", "/api/push/status"),
        ("GET", "/api/notifications/settings"),
        ("PUT", "/api/notifications/settings"),
    ]:
        response = await api.http.request(method, url, headers=anonymous)
        assert response.status_code == 401, url


async def test_subscribe_test_and_unsubscribe(api: Api, servers: FakeServers) -> None:
    phone = await pair_phone(api)
    receiver = Receiver()

    subscribed = await api.http.post(
        "/api/push/subscribe", json=subscription(receiver), headers=phone
    )
    again = await api.http.post("/api/push/subscribe", json=subscription(receiver), headers=phone)
    tested = await api.http.post("/api/push/test", headers=phone)

    assert (subscribed.status_code, again.status_code) == (204, 204)
    assert tested.json() == {"sent": 1, "failed": 0, "removed": 0}
    [request] = servers.to(ENDPOINT)
    assert receiver.read(request.content) == TEST_NOTICE.web_payload()
    [stored] = await api.ctx.notifications.subscriptions.for_device(phone["X-Device"])
    assert stored.endpoint == ENDPOINT

    gone = await api.http.request(
        "DELETE", "/api/push/subscribe", json={"endpoint": ENDPOINT}, headers=phone
    )
    assert gone.status_code == 204
    assert (await api.http.post("/api/push/test", headers=phone)).status_code == 409
    repeat = await api.http.request(
        "DELETE", "/api/push/subscribe", json={"endpoint": ENDPOINT}, headers=phone
    )
    assert repeat.status_code == 204


async def test_a_device_cannot_remove_another_devices_subscription(api: Api) -> None:
    phone = await pair_phone(api)
    await api.http.post("/api/push/subscribe", json=subscription(Receiver()), headers=phone)

    await api.http.request("DELETE", "/api/push/subscribe", json={"endpoint": ENDPOINT})

    assert len(await api.ctx.notifications.subscriptions.for_device(phone["X-Device"])) == 1


@pytest.mark.parametrize(
    "change",
    [
        {"endpoint": "http://push.example/a"},
        {"endpoint": "not a url"},
        # H-05: only the browsers' push services, so the daemon never posts elsewhere.
        {"endpoint": "https://push.example/a"},
        {"endpoint": "https://127.0.0.1:8765/api/sessions"},
        {"endpoint": "https://web.push.apple.com.evil.example/a"},
        {"endpoint": "https://evil.example/web.push.apple.com/a"},
        {"endpoint": "https://push.apple.com/a"},
        {"endpoint": "https://web.push.apple.com:8443/a"},
        {"endpoint": "https://me@web.push.apple.com/a"},
        {"endpoint": "http://web.push.apple.com/a"},
        {"keys": {"p256dh": "AAAA", "auth": b64(bytes(16))}},
        {"keys": {"p256dh": b64(bytes(65)), "auth": b64(bytes(16))}},
        {"keys": {"p256dh": Receiver().p256dh, "auth": b64(bytes(8))}},
        {"keys": {"p256dh": "!!!!", "auth": b64(bytes(16))}},
        {"keys": {"p256dh": Receiver().p256dh}},
    ],
)
async def test_subscriptions_are_validated(api: Api, change: dict[str, JsonValue]) -> None:
    body = subscription(Receiver()) | change

    response = await api.http.post("/api/push/subscribe", json=body)

    assert response.status_code == 422


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://web.push.apple.com/QG/a",
        "https://api.push.apple.com/a",
        "https://fcm.googleapis.com/fcm/send/a",
        "https://updates.push.services.mozilla.com/wpush/v2/a",
        "https://wns2-par02p.notify.windows.com/w/?token=a",
        "https://WEB.PUSH.APPLE.COM:443/a",
    ],
)
async def test_known_push_services_are_accepted(api: Api, endpoint: str) -> None:
    response = await api.http.post("/api/push/subscribe", json=subscription(Receiver(), endpoint))

    assert response.status_code == 204


async def test_revoking_a_device_deletes_its_subscriptions(api: Api) -> None:
    phone = await pair_phone(api)
    await api.http.post("/api/push/subscribe", json=subscription(Receiver()), headers=phone)

    revoked = await api.http.delete(f"/api/devices/{phone['X-Device']}")

    assert revoked.status_code == 204
    assert await api.ctx.notifications.subscriptions.for_device(phone["X-Device"]) == []


async def test_notify_events_reach_subscribed_phones(api: Api, servers: FakeServers) -> None:
    phone = await pair_phone(api)
    receiver = Receiver()
    await api.http.post("/api/push/subscribe", json=subscription(receiver), headers=phone)

    await api.ctx.bus.publish(
        types.NOTIFY,
        {"kind": "failed", "session_id": "s1", "repo": "nest", "title": "T", "text": "boom"},
        "s1",
    )

    await eventually(lambda: len(servers.to(ENDPOINT)) == 1)
    payload = receiver.read(servers.to(ENDPOINT)[0].content)
    assert payload == {
        "title": "Failed · nest",
        "body": "T: boom",
        "url": "/chat/s1",
        "tag": "session-s1",
    }


async def test_notification_settings_round_trip_and_apply_live(api: Api) -> None:
    current = (await api.http.get("/api/notifications/settings")).json()
    assert current["kinds"]["finished"] is True
    assert "quiet_hours" in current
    current["kinds"]["finished"] = False
    current["quiet_hours"] = {"start": "22:00", "end": "07:00"}

    saved = await api.http.put("/api/notifications/settings", json=current)

    assert saved.status_code == 200
    assert saved.json() == current
    assert (await api.http.get("/api/notifications/settings")).json() == current
    assert api.ctx.settings.notifications.kinds.finished is False
    on_disk = tomllib.loads(api.ctx.paths.settings_file.read_text(encoding="utf-8"))
    assert on_disk["notifications"]["quiet_hours"] == {"start": "22:00", "end": "07:00"}
    assert "server" in on_disk


async def test_invalid_notification_settings_are_rejected(api: Api) -> None:
    bad = {"quiet_hours": {"start": "22:00", "end": "22:00"}}

    assert (await api.http.put("/api/notifications/settings", json=bad)).status_code == 422


async def test_a_broken_settings_file_is_reported_not_overwritten(api: Api) -> None:
    api.ctx.paths.settings_file.write_text("[server\n", encoding="utf-8")

    response = await api.http.put("/api/notifications/settings", json={})

    assert response.status_code == 409
    assert "invalid TOML" in response.json()["detail"]


async def test_status_counts_the_devices_with_a_subscription(api: Api) -> None:
    assert (await api.http.get("/api/push/status")).json() == {"devices": 0}
    phone = await pair_phone(api)
    tablet = await pair_phone(api)
    for endpoint in (ENDPOINT, ENDPOINT + "2"):
        await api.http.post(
            "/api/push/subscribe", json=subscription(Receiver(), endpoint), headers=phone
        )
    await api.http.post(
        "/api/push/subscribe", json=subscription(Receiver(), ENDPOINT + "3"), headers=tablet
    )

    assert (await api.http.get("/api/push/status")).json() == {"devices": 2}

    await api.http.delete(f"/api/devices/{tablet['X-Device']}")
    assert (await api.http.get("/api/push/status")).json() == {"devices": 1}
