import asyncio
from collections.abc import AsyncGenerator, Iterator
from pathlib import Path

import pytest
from pydantic import JsonValue
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from harness.api.app import create_app
from harness.context import AppContext
from harness.events import types
from harness.events.bus import EventBus, SubscriptionOverflowError
from harness.events.models import Event
from tests.api_support import build_context, local_token
from tests.fakes import FakeClock, FakeSecretStore


class OverflowingBus(EventBus):
    async def subscribe(self, after_id: int | None = None) -> AsyncGenerator[Event]:
        raise SubscriptionOverflowError("reconnect with after")
        yield  # unreachable; makes this method an async generator like the original


@pytest.fixture
def ctx(tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore) -> Iterator[AppContext]:
    context = asyncio.run(build_context(tmp_path, clock, secrets))
    yield context
    asyncio.run(context.close())


@pytest.fixture
def client(ctx: AppContext) -> Iterator[TestClient]:
    with TestClient(create_app(ctx)) as test_client:
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
    "headers", [{}, {"Authorization": "Bearer wrong"}, {"Cookie": "harness_token=wrong"}]
)
def test_unauthenticated_socket_is_closed_with_4401(
    client: TestClient, headers: dict[str, str]
) -> None:
    expect_close(client, "/api/events", 4401, headers=headers)


def test_replays_after_id_then_streams_live_events(
    client: TestClient, ctx: AppContext, secrets: FakeSecretStore
) -> None:
    auth = {"Authorization": f"Bearer {local_token(secrets)}"}
    with client.websocket_connect("/api/events?after=0", headers=auth) as ws:
        started = ws.receive_json()
        live = publish(client, ctx, "live.event")
        received = ws.receive_json()

    assert started["type"] == types.DAEMON_STARTED
    assert started["id"] == 1
    assert received == live.model_dump(mode="json")


def test_cookie_auth_and_live_only_without_after(
    client: TestClient, ctx: AppContext, secrets: FakeSecretStore
) -> None:
    cookie = {"Cookie": f"harness_token={local_token(secrets)}"}
    with client.websocket_connect("/api/events", headers=cookie) as ws:
        ws.send_text("ignored")
        live = publish(client, ctx, "live.only")
        assert ws.receive_json()["id"] == live.id


def test_disconnect_releases_the_subscription(
    client: TestClient, ctx: AppContext, secrets: FakeSecretStore
) -> None:
    auth = {"Authorization": f"Bearer {local_token(secrets)}"}
    with client.websocket_connect("/api/events", headers=auth):
        pass

    assert client.portal is not None
    client.portal.call(asyncio.sleep, 0)
    assert ctx.bus.subscriber_count == 0


def test_overflow_closes_the_socket_with_try_again_later(
    client: TestClient, ctx: AppContext, secrets: FakeSecretStore
) -> None:
    ctx.bus = OverflowingBus(ctx.db, ctx.clock)
    auth = {"Authorization": f"Bearer {local_token(secrets)}"}

    expect_close(client, "/api/events?after=0", 1013, headers=auth)


def test_invalid_after_is_rejected(client: TestClient, secrets: FakeSecretStore) -> None:
    auth = {"Authorization": f"Bearer {local_token(secrets)}"}

    with (
        pytest.raises(WebSocketDisconnect) as closed,
        client.websocket_connect("/api/events?after=-1", headers=auth),
    ):
        pass

    assert closed.value.code == 1008
