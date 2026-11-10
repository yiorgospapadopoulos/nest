"""B159 R07: a cookie login changes nothing from another host's page (same site, the
tailnet); Nest's own page and Bearer clients keep working.
"""

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

from nestd.api.app import create_app
from nestd.context import AppContext
from tests.api_support import build_context, local_token
from tests.fakes import FakeClock, FakeSecretStore, RecordingRestart

HOST = "mac.tailnet.ts.net"
# Any route that changes something and needs a device.
CHANGE = "/api/pairing/codes"


@pytest.fixture
async def client(
    tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore
) -> AsyncIterator[httpx.AsyncClient]:
    ctx: AppContext = await build_context(tmp_path, clock, secrets)
    app = create_app(ctx, restart=RecordingRestart())
    transport = httpx.ASGITransport(app=app)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=transport, base_url=f"https://{HOST}") as http,
    ):
        yield http
    await ctx.close()


@pytest.mark.parametrize("name", ["nest_token", "harness_token"])
@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "https://evil.tailnet.ts.net"},
        {"Origin": f"https://{HOST}.evil.net"},
        {"Origin": "null"},
        {"Sec-Fetch-Site": "same-site", "Origin": "https://evil.tailnet.ts.net"},
        {},
    ],
)
async def test_a_cookie_post_from_another_page_is_refused(
    client: httpx.AsyncClient, secrets: FakeSecretStore, name: str, headers: dict[str, str]
) -> None:
    cookie = {"Cookie": f"{name}={local_token(secrets)}"}

    response = await client.post(CHANGE, headers={**cookie, **headers})

    assert response.status_code == 403


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": f"https://{HOST}"},
        # `tailscale serve` takes https; the scheme does not have to match.
        {"Origin": f"http://{HOST}"},
        {"Sec-Fetch-Site": "same-origin"},
    ],
)
async def test_a_cookie_post_from_nests_own_page_works(
    client: httpx.AsyncClient, secrets: FakeSecretStore, headers: dict[str, str]
) -> None:
    cookie = {"Cookie": f"nest_token={local_token(secrets)}"}

    response = await client.post(CHANGE, headers={**cookie, **headers})

    assert response.status_code == 200


async def test_cookie_reads_and_bearer_changes_need_no_origin(
    client: httpx.AsyncClient, secrets: FakeSecretStore
) -> None:
    token = local_token(secrets)
    foreign = {"Origin": "https://evil.tailnet.ts.net"}

    read = await client.get("/api/devices", headers={"Cookie": f"nest_token={token}", **foreign})
    bearer = await client.post(
        CHANGE,
        headers={"Authorization": f"Bearer {token}", "Cookie": f"nest_token={token}", **foreign},
    )

    assert read.status_code == 200
    assert bearer.status_code == 200
