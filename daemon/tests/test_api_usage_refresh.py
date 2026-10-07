import tomllib
from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path

import pytest

from harness.usage.refresher import FORCED_SPACING
from harness.usage.visibility import VISIBILITY_TTL
from tests.api_client import Api, running_api
from tests.async_support import until
from tests.fake_probe import answer, result
from tests.fakes import FakeClock, FakeSecretStore
from tests.test_api_push import pair_phone


@pytest.fixture
async def api(tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore) -> AsyncIterator[Api]:
    async with running_api(tmp_path, clock, secrets) as running:
        yield running


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/usage/refresh"),
        ("GET", "/api/usage/settings"),
        ("PUT", "/api/usage/settings"),
        ("POST", "/api/clients/visibility"),
    ],
)
async def test_routes_require_a_device_token(api: Api, method: str, path: str) -> None:
    response = await api.http.request(method, path, headers={"Authorization": "Bearer wrong"})

    assert response.status_code == 401


async def test_refresh_probes_and_returns_the_new_limits(api: Api, clock: FakeClock) -> None:
    api.probes.replies.append(answer(0.42, 0.12))

    response = await api.http.post("/api/usage/refresh")

    assert response.status_code == 200
    body = response.json()
    assert body["five_hour"]["utilization"] == 0.42
    assert body["seven_day"]["utilization"] == 0.12
    assert body["five_hour"]["updated_at"] == clock.now().isoformat().replace("+00:00", "Z")
    assert (await api.http.get("/api/usage/limits")).json() == body
    month = (await api.http.get("/api/usage/month", params={"year": 2026, "month": 1})).json()
    assert (month["sessions"], month["tokens"]["total"]) == (0, 0)
    assert month["probes"] == {"count": 1, "tokens": 452}


async def test_refresh_is_rate_limited(api: Api, clock: FakeClock) -> None:
    api.probes.replies.extend([answer(), answer()])
    await api.http.post("/api/usage/refresh")
    clock.advance(FORCED_SPACING / 2)

    response = await api.http.post("/api/usage/refresh")

    assert response.status_code == 429
    assert response.headers["retry-after"] == "10"
    assert response.json()["retry_after"] == 10
    assert api.probes.prompts == 1


async def test_a_failed_refresh_answers_502(api: Api) -> None:
    api.probes.replies.append([result()])

    response = await api.http.post("/api/usage/refresh")

    assert response.status_code == 502
    assert "did not report" in response.json()["detail"]


async def test_a_visible_client_starts_the_probes(api: Api) -> None:
    api.probes.replies.append(answer(0.3))
    phone = await pair_phone(api)

    response = await api.http.post(
        "/api/clients/visibility", json={"visible": True, "client": "pwa"}, headers=phone
    )

    assert response.status_code == 204

    async def probed() -> bool:
        limits = (await api.http.get("/api/usage/limits", headers=phone)).json()
        return limits["five_hour"] is not None

    await until(probed)
    assert api.probes.prompts == 1


async def test_hidden_and_lapsed_clients_are_not_visible(api: Api, clock: FakeClock) -> None:
    visibility = api.ctx.usage_refresher.visibility
    await api.http.post("/api/clients/visibility", json={"visible": True})
    phone = await pair_phone(api)
    await api.http.post("/api/clients/visibility", json={"visible": True}, headers=phone)

    await api.http.post("/api/clients/visibility", json={"visible": False})
    assert visibility.any_visible()

    clock.advance(VISIBILITY_TTL)
    assert not visibility.any_visible()


@pytest.mark.parametrize("body", [{}, {"visible": "maybe"}, {"visible": True, "client": "a b"}])
async def test_visibility_reports_are_validated(api: Api, body: dict[str, object]) -> None:
    assert (await api.http.post("/api/clients/visibility", json=body)).status_code == 422


async def test_refresh_interval_round_trips_and_applies_live(api: Api) -> None:
    assert (await api.http.get("/api/usage/settings")).json() == {"refresh_minutes": 3}

    saved = await api.http.put("/api/usage/settings", json={"refresh_minutes": 0})

    assert saved.status_code == 200
    assert saved.json() == {"refresh_minutes": 0}
    assert api.ctx.settings.usage.refresh_minutes == 0
    assert api.ctx.usage_interval() is None
    on_disk = tomllib.loads(api.ctx.paths.settings_file.read_text(encoding="utf-8"))
    assert on_disk["usage"] == {"refresh_minutes": 0}
    await api.http.put("/api/usage/settings", json={"refresh_minutes": 5})
    assert api.ctx.usage_interval() == timedelta(minutes=5)


@pytest.mark.parametrize("body", [{"refresh_minutes": -1}, {"refresh_minutes": 3, "x": 1}])
async def test_invalid_refresh_settings_are_rejected(api: Api, body: dict[str, int]) -> None:
    assert (await api.http.put("/api/usage/settings", json=body)).status_code == 422


async def test_a_broken_settings_file_is_reported_not_overwritten(api: Api) -> None:
    api.ctx.paths.settings_file.write_text("[usage\n", encoding="utf-8")

    response = await api.http.put("/api/usage/settings", json={"refresh_minutes": 1})

    assert response.status_code == 409
    assert api.ctx.paths.settings_file.read_text(encoding="utf-8") == "[usage\n"
