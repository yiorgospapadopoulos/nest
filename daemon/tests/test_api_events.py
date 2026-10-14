import asyncio
from collections.abc import AsyncGenerator, Iterator
from pathlib import Path

import pytest
from pydantic import JsonValue
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from nestd.api.app import create_app
from nestd.api.routes.events import origin_allowed
from nestd.context import AppContext
from nestd.events import types
from nestd.events.bus import EventBus, SubscriptionOverflowError
from nestd.events.models import Event
from tests.api_support import build_context, local_token
from tests.fakes import FakeClock, FakeSecretStore


class OverflowingBus(EventBus):
    async def subscribe(self, after_id: int | None = None) -> AsyncGenerator[Event]:
        raise SubscriptionOverflowError("reconnect with after")
        yield  # unreachable; makes this method an async generator like the original


# The iPhone reaches the daemon by its tailnet name through `tailscale serve`.
BASE_URL = "https://mac.tailnet.ts.net"


@pytest.fixture
def ctx(tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore) -> Iterator[AppContext]:
    context = asyncio.run(build_context(tmp_path, clock, secrets))
    yield context
    asyncio.run(context.close())


@pytest.fixture
def client(ctx: AppContext) -> Iterator[TestClient]:
    with TestClient(create_app(ctx), base_url=BASE_URL) as test_client:
        yield test_client


def publish(client: TestClient, ctx: AppContext, event_type: str) -> Event:
    assert client.portal is not None
    payload: dict[str, JsonValue] = {}
    return client.portal.call(ctx.bus.publish, event_type, payload)


def expect_close(client: TestClient, url: str, code: int, headers: dict[str, str]) -> None:
    with client.websocket_connect(url, headers=headers) as ws:
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
        assert closed.value.code == code


@pytest.mark.parametrize(
    "headers", [{}, {"Authorization": "Bearer wrong"}, {"Cookie": "nest_token=wrong"}]
)
def test_unauthenticated_socket_is_closed_with_4401(
    client: TestClient, headers: dict[str, str]
) -> None:
    expect_close(client, "wss://mac.tailnet.ts.net/api/events", 4401, headers=headers)


def test_replays_after_id_then_streams_live_events(
    client: TestClient, ctx: AppContext, secrets: FakeSecretStore
) -> None:
    auth = {"Authorization": f"Bearer {local_token(secrets)}"}
    stored = publish(client, ctx, "stored.event")
    with client.websocket_connect(
        "wss://mac.tailnet.ts.net/api/events?after=0", headers=auth
    ) as ws:
        replayed = ws.receive_json()
        live = publish(client, ctx, "live.event")
        received = ws.receive_json()

    assert replayed == stored.model_dump(mode="json")
    assert replayed["id"] == 1
    assert received == live.model_dump(mode="json")


def test_cookie_auth_and_live_only_without_after(
    client: TestClient, ctx: AppContext, secrets: FakeSecretStore
) -> None:
    cookie = {"Cookie": f"nest_token={local_token(secrets)}"}
    with client.websocket_connect("wss://mac.tailnet.ts.net/api/events", headers=cookie) as ws:
        ws.send_text("ignored")
        live = publish(client, ctx, "live.only")
        assert ws.receive_json()["id"] == live.id


@pytest.mark.parametrize("name", ["nest_token", "harness_token"])
def test_the_cookie_from_before_the_rename_still_authenticates(
    client: TestClient, ctx: AppContext, secrets: FakeSecretStore, name: str
) -> None:
    """B43: a phone paired before the rename keeps its `harness_token` cookie."""
    cookie = {"Cookie": f"{name}={local_token(secrets)}"}
    with client.websocket_connect("wss://mac.tailnet.ts.net/api/events", headers=cookie) as ws:
        live = publish(client, ctx, "live.only")
        assert ws.receive_json()["id"] == live.id


def test_disconnect_releases_the_subscription(
    client: TestClient, ctx: AppContext, secrets: FakeSecretStore
) -> None:
    auth = {"Authorization": f"Bearer {local_token(secrets)}"}
    # The notification delivery follows the bus too.
    before = ctx.bus.subscriber_count
    with client.websocket_connect("wss://mac.tailnet.ts.net/api/events", headers=auth):
        pass

    assert client.portal is not None
    client.portal.call(asyncio.sleep, 0)
    assert ctx.bus.subscriber_count == before


def paired_phone(client: TestClient, local: dict[str, str]) -> tuple[str, str]:
    code = client.post("/api/pairing/codes", headers=local).json()["code"]
    redeemed = client.post("/api/pairing/redeem", json={"code": code, "device_name": "Phone"})
    body = redeemed.json()
    return body["device"]["id"], body["token"]


def test_revoking_a_device_closes_its_open_sockets_only(
    client: TestClient, secrets: FakeSecretStore
) -> None:
    """D051: a revoked phone stops receiving events at once, the Mac's socket goes on."""
    local = {"Authorization": f"Bearer {local_token(secrets)}"}
    phone_id, phone_token = paired_phone(client, local)
    phone = {"Authorization": f"Bearer {phone_token}"}

    with (
        client.websocket_connect("wss://mac.tailnet.ts.net/api/events", headers=phone) as phone_ws,
        client.websocket_connect("wss://mac.tailnet.ts.net/api/events", headers=local) as mac_ws,
    ):
        assert client.delete(f"/api/devices/{phone_id}", headers=local).status_code == 204
        with pytest.raises(WebSocketDisconnect) as closed:
            phone_ws.receive_json()
        revoked = mac_ws.receive_json()

    assert closed.value.code == 4401
    assert (revoked["type"], revoked["payload"]) == (
        types.DEVICE_REVOKED,
        {"device_id": phone_id},
    )


def test_overflow_closes_the_socket_with_try_again_later(
    client: TestClient, ctx: AppContext, secrets: FakeSecretStore
) -> None:
    ctx.bus = OverflowingBus(ctx.db, ctx.clock)
    auth = {"Authorization": f"Bearer {local_token(secrets)}"}

    expect_close(client, "wss://mac.tailnet.ts.net/api/events?after=0", 1013, headers=auth)


def test_invalid_after_is_rejected(client: TestClient, secrets: FakeSecretStore) -> None:
    auth = {"Authorization": f"Bearer {local_token(secrets)}"}

    with (
        pytest.raises(WebSocketDisconnect) as closed,
        client.websocket_connect("wss://mac.tailnet.ts.net/api/events?after=-1", headers=auth),
    ):
        pass

    assert closed.value.code == 1008


@pytest.mark.parametrize(
    "origin",
    ["https://mac.tailnet.ts.net", "HTTPS://Mac.Tailnet.TS.net", "http://mac.tailnet.ts.net"],
)
def test_same_origin_browsers_are_accepted(
    client: TestClient, ctx: AppContext, secrets: FakeSecretStore, origin: str
) -> None:
    headers = {"Authorization": f"Bearer {local_token(secrets)}", "Origin": origin}
    with client.websocket_connect("wss://mac.tailnet.ts.net/api/events", headers=headers) as ws:
        live = publish(client, ctx, "same.origin")
        assert ws.receive_json()["id"] == live.id


@pytest.mark.parametrize(
    "origin",
    [
        "https://evil.example",
        "https://mac.tailnet.ts.net.evil.example",
        "null",
        "file://mac.tailnet.ts.net",
        "",
    ],
)
def test_cross_origin_sockets_are_closed_with_4403(
    client: TestClient, secrets: FakeSecretStore, origin: str
) -> None:
    headers = {"Authorization": f"Bearer {local_token(secrets)}", "Origin": origin}

    expect_close(client, "wss://mac.tailnet.ts.net/api/events", 4403, headers=headers)


def test_cross_origin_check_runs_before_authentication(client: TestClient) -> None:
    expect_close(
        client,
        "wss://mac.tailnet.ts.net/api/events",
        4403,
        headers={"Origin": "https://evil.example"},
    )


def test_allowed_origins_from_settings_are_accepted(
    tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore
) -> None:
    settings = tmp_path / "config" / "settings.toml"
    settings.parent.mkdir(parents=True)
    settings.write_text(
        '[server]\nallowed_origins = ["https://mac.example.ts.net"]\n', encoding="utf-8"
    )
    context = asyncio.run(build_context(tmp_path, clock, secrets))
    try:
        with TestClient(create_app(context), base_url=BASE_URL) as test_client:
            headers = {
                "Authorization": f"Bearer {local_token(secrets)}",
                "Origin": "https://mac.example.ts.net",
            }
            with test_client.websocket_connect(
                "wss://mac.tailnet.ts.net/api/events", headers=headers
            ) as ws:
                live = publish(test_client, context, "allowed.origin")
                assert ws.receive_json()["id"] == live.id
            other = {**headers, "Origin": "https://x.y"}
            expect_close(test_client, "wss://mac.tailnet.ts.net/api/events", 4403, other)
    finally:
        asyncio.run(context.close())


@pytest.mark.parametrize(
    ("origin", "host", "allowed", "expected"),
    [
        (None, None, [], True),
        ("https://mac.example.ts.net", None, [], False),
        ("https://mac.example.ts.net/", None, ["HTTPS://Mac.Example.ts.net/"], True),
        ("http://127.0.0.1:18766", "127.0.0.1:18766", [], True),
        ("http://127.0.0.1:18766", "127.0.0.1:8765", [], False),
        ("ws://127.0.0.1:8765", "127.0.0.1:8765", [], False),
    ],
)
def test_origin_rules(
    origin: str | None, host: str | None, allowed: list[str], expected: bool
) -> None:
    assert origin_allowed(origin, host, allowed) is expected
