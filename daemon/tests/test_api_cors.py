"""B117: the desktop app's page calls the API from its own origin with a Bearer token."""

import asyncio
from collections.abc import Iterator
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from nestd.api.app import create_app
from nestd.context import AppContext
from tests.api_support import build_context, local_token
from tests.fakes import FakeClock, FakeSecretStore, RecordingRestart

TAURI_ORIGINS = ["tauri://localhost", "http://tauri.localhost"]
PREFLIGHT = {
    "Access-Control-Request-Method": "POST",
    "Access-Control-Request-Headers": "authorization, content-type",
}


@pytest.fixture
def ctx(tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore) -> Iterator[AppContext]:
    settings = tmp_path / "config" / "settings.toml"
    settings.parent.mkdir(parents=True)
    settings.write_text(
        '[server]\nallowed_origins = ["https://mac.example.ts.net"]\n', encoding="utf-8"
    )
    context = asyncio.run(build_context(tmp_path, clock, secrets))
    yield context
    asyncio.run(context.close())


@pytest.fixture
def client(ctx: AppContext) -> Iterator[TestClient]:
    app = create_app(ctx, restart=RecordingRestart())
    with TestClient(app, base_url="http://127.0.0.1:8765") as test_client:
        yield test_client


def cors_headers(headers: dict[str, str]) -> dict[str, str]:
    return {name: value for name, value in headers.items() if name.startswith("access-control-")}


@pytest.mark.parametrize("origin", [*TAURI_ORIGINS, "https://mac.example.ts.net"])
def test_a_preflight_from_an_allowed_origin_passes_without_a_token(
    client: TestClient, origin: str
) -> None:
    response = client.options("/api/devices", headers={"Origin": origin, **PREFLIGHT})

    assert response.status_code == 204
    headers = cors_headers(dict(response.headers))
    assert headers["access-control-allow-origin"] == origin
    assert {"authorization", "content-type"} <= {
        name.strip().lower() for name in headers["access-control-allow-headers"].split(",")
    }
    assert {"GET", "POST", "PUT", "PATCH", "DELETE"} <= {
        method.strip() for method in headers["access-control-allow-methods"].split(",")
    }
    # The token goes in a header, never a cookie, so no credentials mode.
    assert "access-control-allow-credentials" not in headers
    assert "origin" in response.headers["vary"].lower()


@pytest.mark.parametrize("origin", TAURI_ORIGINS)
def test_responses_to_an_allowed_origin_can_be_read_by_its_page(
    client: TestClient, secrets: FakeSecretStore, origin: str
) -> None:
    auth = {"Authorization": f"Bearer {local_token(secrets)}", "Origin": origin}

    listed = client.get("/api/devices", headers=auth)
    refused = client.get("/api/devices", headers={"Origin": origin})

    assert listed.status_code == 200
    assert listed.headers["access-control-allow-origin"] == origin
    # The page can tell a lost token from a network failure.
    assert refused.status_code == 401
    assert refused.headers["access-control-allow-origin"] == origin
    assert "access-control-allow-credentials" not in listed.headers


@pytest.mark.parametrize(
    "origin",
    [
        "https://evil.example",
        "tauri://localhost.evil.example",
        "tauri://evil",
        "https://tauri.localhost",
        "http://tauri.localhost:8080",
        "null",
    ],
)
def test_any_other_origin_gets_no_cors_headers(
    client: TestClient, secrets: FakeSecretStore, origin: str
) -> None:
    preflight = client.options("/api/devices", headers={"Origin": origin, **PREFLIGHT})
    auth = {"Authorization": f"Bearer {local_token(secrets)}", "Origin": origin}
    listed = client.get("/api/devices", headers=auth)

    assert cors_headers(dict(preflight.headers)) == {}
    assert preflight.status_code != 204
    assert cors_headers(dict(listed.headers)) == {}
