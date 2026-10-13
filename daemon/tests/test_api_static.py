from collections.abc import AsyncIterator
from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from harness.api.app import create_app
from harness.context import AppContext
from tests.api_support import build_context, local_token
from tests.fakes import FakeClock, FakeSecretStore

INDEX = "<!doctype html><title>harness</title>"
IMMUTABLE = "public, max-age=31536000, immutable"


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    root = tmp_path / "dist"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text(INDEX, encoding="utf-8")
    (root / "sw.js").write_text("self.addEventListener('fetch', () => {});", encoding="utf-8")
    (root / "manifest.webmanifest").write_text('{"name": "harness"}', encoding="utf-8")
    (root / "icon-192.png").write_bytes(b"\x89PNG")
    (root / "assets" / "index-abc123.js").write_text("console.log(1);", encoding="utf-8")
    (root / "assets" / "index-abc123.css").write_text("body{}", encoding="utf-8")
    return root


async def serving(ctx: AppContext) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(ctx)
    transport = httpx.ASGITransport(app=app)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=transport, base_url="https://mac.tailnet.ts.net") as http,
    ):
        yield http


@pytest.fixture
async def ctx(
    tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore, dist: Path
) -> AsyncIterator[AppContext]:
    context = await build_context(tmp_path, clock, secrets)
    context.paths = replace(context.paths, web_dist=dist)
    yield context
    await context.close()


@pytest.fixture
async def client(ctx: AppContext) -> AsyncIterator[httpx.AsyncClient]:
    async for http in serving(ctx):
        yield http


async def test_root_serves_the_app_shell_without_auth_and_uncached(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/")

    assert response.status_code == 200
    assert response.text == INDEX
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["cache-control"] == "no-cache"


@pytest.mark.parametrize("path", ["/inbox", "/projects/harness/chat", "/assets"])
async def test_unknown_app_paths_fall_back_to_the_index(
    client: httpx.AsyncClient, path: str
) -> None:
    response = await client.get(path)

    assert response.status_code == 200
    assert response.text == INDEX
    assert response.headers["cache-control"] == "no-cache"


async def test_hashed_assets_are_cached_for_a_long_time(client: httpx.AsyncClient) -> None:
    script = await client.get("/assets/index-abc123.js")
    style = await client.get("/assets/index-abc123.css")

    assert script.text == "console.log(1);"
    assert script.headers["content-type"].startswith("text/javascript")
    assert script.headers["cache-control"] == IMMUTABLE
    assert style.headers["content-type"].startswith("text/css")
    assert style.headers["cache-control"] == IMMUTABLE


@pytest.mark.parametrize(
    ("path", "media_type"),
    [
        ("/sw.js", "text/javascript"),
        ("/manifest.webmanifest", "application/manifest+json"),
        ("/icon-192.png", "image/png"),
    ],
)
async def test_unhashed_files_are_revalidated(
    client: httpx.AsyncClient, path: str, media_type: str
) -> None:
    response = await client.get(path)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith(media_type)
    assert response.headers["cache-control"] == "no-cache"


async def test_head_requests_are_answered(client: httpx.AsyncClient) -> None:
    response = await client.head("/")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"


@pytest.mark.parametrize("path", ["/assets/missing-123.js", "/favicon.ico"])
async def test_missing_files_are_not_found(client: httpx.AsyncClient, path: str) -> None:
    assert (await client.get(path)).status_code == 404


@pytest.mark.parametrize("path", ["/../secret.txt", "/assets/..%2F..%2Fsecret.txt"])
async def test_paths_cannot_escape_the_dist_folder(
    client: httpx.AsyncClient, tmp_path: Path, path: str
) -> None:
    (tmp_path / "secret.txt").write_text("secret", encoding="utf-8")

    response = await client.get(path)

    assert "secret" not in response.text


async def test_api_routes_keep_priority(
    client: httpx.AsyncClient, secrets: FakeSecretStore
) -> None:
    auth = {"Authorization": f"Bearer {local_token(secrets)}"}

    health = await client.get("/api/health")
    repos = await client.get("/api/repos", headers=auth)

    assert health.json()["status"] == "ok"
    assert repos.json() == []


@pytest.mark.parametrize("path", ["/api", "/api/unknown", "/api/sessions/x/unknown"])
async def test_unknown_api_paths_are_not_found_as_json(
    client: httpx.AsyncClient, path: str
) -> None:
    response = await client.get(path)

    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


async def test_without_a_build_nothing_is_served(
    tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore
) -> None:
    context = await build_context(tmp_path, clock, secrets)
    context.paths = replace(context.paths, web_dist=tmp_path / "missing")
    try:
        async for http in serving(context):
            assert (await http.get("/")).status_code == 404
            assert (await http.get("/inbox")).status_code == 404
    finally:
        await context.close()
