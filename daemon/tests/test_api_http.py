from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

import harness
from harness.api.app import create_app
from harness.config.errors import ConfigError
from harness.context import AppContext
from harness.events import types
from tests.api_support import build_context, local_token, make_paths
from tests.fakes import FakeClock, FakeSecretStore


@pytest.fixture
async def ctx(
    tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore
) -> AsyncIterator[AppContext]:
    context = await build_context(tmp_path, clock, secrets)
    yield context
    await context.close()


@pytest.fixture
async def client(ctx: AppContext) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(ctx)
    transport = httpx.ASGITransport(app=app)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=transport, base_url="https://testserver") as http,
    ):
        yield http


@pytest.fixture
def auth(secrets: FakeSecretStore, client: httpx.AsyncClient) -> dict[str, str]:
    return {"Authorization": f"Bearer {local_token(secrets)}"}


async def run_lifespan(app: FastAPI) -> None:
    async with app.router.lifespan_context(app):
        pass


async def event_types(ctx: AppContext) -> list[str]:
    rows = await ctx.db.fetch_all("SELECT type FROM events ORDER BY id")
    return [row["type"] for row in rows]


async def test_health_needs_no_auth(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": harness.__version__}


async def test_startup_creates_local_token_and_publishes_daemon_started(
    client: httpx.AsyncClient, ctx: AppContext, secrets: FakeSecretStore
) -> None:
    assert local_token(secrets)
    rows = await ctx.db.fetch_all("SELECT type, payload FROM events")
    assert [(row["type"], row["payload"]) for row in rows] == [
        (types.DAEMON_STARTED, f'{{"version": "{harness.__version__}"}}')
    ]


async def test_lifespan_starts_and_stops_enabled_modules(
    tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore
) -> None:
    log: list[str] = []
    ctx = await build_context(tmp_path, clock, secrets, log)
    app = create_app(ctx)
    try:
        async with app.router.lifespan_context(app):
            assert log == ["start 8765"]
        assert log == ["start 8765", "stop"]
    finally:
        await ctx.close()


async def test_unknown_enabled_module_fails_startup(
    tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore
) -> None:
    ctx = await AppContext.build(make_paths(tmp_path, ["missing"]), secrets, clock)
    app = create_app(ctx)
    try:
        with pytest.raises(ConfigError, match="unknown modules: missing"):
            await run_lifespan(app)
    finally:
        await ctx.close()


async def test_api_docs_are_not_exposed(client: httpx.AsyncClient) -> None:
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert (await client.get(path)).status_code == 404


@pytest.mark.parametrize(
    ("method", "path"),
    [("POST", "/api/pairing/codes"), ("GET", "/api/devices"), ("DELETE", "/api/devices/x")],
)
@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Bearer wrong"}, {"Authorization": "Basic abc"}, {"Cookie": "x=y"}],
)
async def test_protected_routes_reject_missing_or_bad_credentials(
    client: httpx.AsyncClient, method: str, path: str, headers: dict[str, str]
) -> None:
    response = await client.request(method, path, headers=headers)

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


async def test_create_pairing_code(
    client: httpx.AsyncClient, auth: dict[str, str], clock: FakeClock
) -> None:
    response = await client.post("/api/pairing/codes", headers=auth)

    assert response.status_code == 200
    body = response.json()
    assert len(body["code"]) == 8
    assert body["expires_at"] == (clock.current + timedelta(minutes=5)).isoformat().replace(
        "+00:00", "Z"
    )


async def test_redeem_sets_cookie_and_the_cookie_authenticates(
    client: httpx.AsyncClient, auth: dict[str, str], ctx: AppContext
) -> None:
    code = (await client.post("/api/pairing/codes", headers=auth)).json()["code"]

    response = await client.post(
        "/api/pairing/redeem", json={"code": code.lower(), "device_name": "  iPhone  "}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["device"]["name"] == "iPhone"
    assert body["device"]["is_local"] is False
    cookie = response.headers["set-cookie"]
    assert cookie.startswith(f"harness_token={body['token']};")
    for attribute in ("HttpOnly", "Secure", "SameSite=strict", "Max-Age=34560000", "Path=/"):
        assert attribute in cookie
    devices = await client.get("/api/devices")
    assert devices.status_code == 200
    assert [d["name"] for d in devices.json()] == ["This Mac", "iPhone"]
    assert (await event_types(ctx))[-1] == types.DEVICE_PAIRED
    last = await ctx.db.fetch_one("SELECT payload FROM events ORDER BY id DESC LIMIT 1")
    assert last is not None
    assert last["payload"] == f'{{"device_id": "{body["device"]["id"]}", "name": "iPhone"}}'


async def test_redeem_rejects_bad_codes_then_locks_out(client: httpx.AsyncClient) -> None:
    payload = {"code": "WRONGONE", "device_name": "phone"}
    for _ in range(5):
        response = await client.post("/api/pairing/redeem", json=payload)
        assert response.status_code == 400
        assert response.json() == {"detail": "invalid or expired pairing code"}

    locked = await client.post("/api/pairing/redeem", json=payload)

    assert locked.status_code == 429
    assert locked.headers["retry-after"] == "300"


@pytest.mark.parametrize(
    "payload",
    [{"code": "ABCDEFGH", "device_name": "   "}, {"code": "", "device_name": "x"}, {"code": "A"}],
)
async def test_redeem_validates_input(client: httpx.AsyncClient, payload: dict[str, str]) -> None:
    response = await client.post("/api/pairing/redeem", json=payload)

    assert response.status_code == 422


async def test_revoke_device(
    client: httpx.AsyncClient, auth: dict[str, str], ctx: AppContext
) -> None:
    code = (await client.post("/api/pairing/codes", headers=auth)).json()["code"]
    redeemed = (
        await client.post("/api/pairing/redeem", json={"code": code, "device_name": "phone"})
    ).json()
    client.cookies.clear()
    phone = {"Authorization": f"Bearer {redeemed['token']}"}

    response = await client.delete(f"/api/devices/{redeemed['device']['id']}", headers=auth)

    assert response.status_code == 204
    assert (await client.get("/api/devices", headers=phone)).status_code == 401
    assert [d["name"] for d in (await client.get("/api/devices", headers=auth)).json()] == [
        "This Mac"
    ]
    assert (await event_types(ctx))[-1] == types.DEVICE_REVOKED
    again = await client.delete(f"/api/devices/{redeemed['device']['id']}", headers=auth)
    assert again.status_code == 404
    assert (await event_types(ctx)).count(types.DEVICE_REVOKED) == 1
