"""H-02: only requests addressed to this Mac's own names reach the API (DNS rebinding)."""

import asyncio
from collections.abc import Iterator
from pathlib import Path

import pytest
from pydantic import JsonValue
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from nestd.api.app import create_app
from nestd.api.hosts import host_allowed
from nestd.context import AppContext
from tests.api_support import build_context, local_token
from tests.fakes import FakeClock, FakeSecretStore, RecordingRestart


def app_client(
    tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore, settings: str = ""
) -> Iterator[tuple[TestClient, AppContext]]:
    if settings:
        path = tmp_path / "config" / "settings.toml"
        path.parent.mkdir(parents=True)
        path.write_text(settings, encoding="utf-8")
    context = asyncio.run(build_context(tmp_path, clock, secrets))
    try:
        with TestClient(
            create_app(context, restart=RecordingRestart()), base_url="http://127.0.0.1:8765"
        ) as client:
            yield client, context
    finally:
        asyncio.run(context.close())


@pytest.fixture
def served(
    tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore
) -> Iterator[tuple[TestClient, AppContext]]:
    yield from app_client(tmp_path, clock, secrets)


@pytest.fixture
def client(served: tuple[TestClient, AppContext]) -> TestClient:
    return served[0]


@pytest.mark.parametrize(
    "host",
    [
        "127.0.0.1:8765",
        "127.0.0.1",
        "localhost:8765",
        "LOCALHOST",
        "[::1]:8765",
        "[::1]",
        # `tailscale serve` passes the tailnet name through.
        "mac.tail1234.ts.net",
        "Mac.Tail1234.TS.NET.",
    ],
)
def test_own_names_are_served(client: TestClient, host: str) -> None:
    response = client.get("/api/health", headers={"Host": host})

    assert response.status_code == 200


@pytest.mark.parametrize(
    "host",
    [
        "evil.example",
        "evil.example:8765",
        "ts.net",
        "ts.net.evil.example",
        "mac.ts.net.evil.example",
        "127.0.0.1.evil.example",
        "localhost.evil.example",
        "10.0.0.5:8765",
        "[::2]:8765",
        "[::1",
        "",
    ],
)
def test_other_hosts_are_refused(client: TestClient, host: str) -> None:
    response = client.get("/api/health", headers={"Host": host})

    assert response.status_code == 400
    assert response.text == "Invalid host header"


def test_static_files_are_checked_too(client: TestClient) -> None:
    assert client.get("/", headers={"Host": "evil.example"}).status_code == 400


def test_sockets_with_another_host_are_refused_before_accepting(
    client: TestClient, secrets: FakeSecretStore
) -> None:
    headers = {"Authorization": f"Bearer {local_token(secrets)}", "Host": "evil.example"}

    with (
        pytest.raises(WebSocketDisconnect) as closed,
        client.websocket_connect("ws://127.0.0.1:8765/api/events", headers=headers),
    ):
        pass

    assert closed.value.code == 1008


def test_sockets_to_the_tailnet_name_are_accepted(
    served: tuple[TestClient, AppContext], secrets: FakeSecretStore
) -> None:
    client, ctx = served
    headers = {
        "Authorization": f"Bearer {local_token(secrets)}",
        "Host": "mac.tail1234.ts.net",
        "Origin": "https://mac.tail1234.ts.net",
    }

    with client.websocket_connect("ws://127.0.0.1:8765/api/events", headers=headers) as ws:
        assert client.portal is not None
        payload: dict[str, JsonValue] = {}
        live = client.portal.call(ctx.bus.publish, "over.tailnet", payload)
        assert ws.receive_json()["id"] == live.id


def test_allowed_hosts_from_settings_are_served(
    tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore
) -> None:
    settings = '[server]\nallowed_hosts = ["nest.home.arpa", "*.example.org"]\n'
    for client, _ctx in app_client(tmp_path, clock, secrets, settings):
        for host in ("nest.home.arpa:8765", "mac.example.org", "a.b.example.org"):
            assert client.get("/api/health", headers={"Host": host}).status_code == 200
        for host in ("example.org", "nest.home.arpa.evil", "evil.example"):
            assert client.get("/api/health", headers={"Host": host}).status_code == 400
        # The built-in names stay allowed.
        assert client.get("/api/health", headers={"Host": "localhost"}).status_code == 200


def test_a_request_without_a_host_header_is_refused() -> None:
    assert host_allowed(None, []) is False
