"""What new pixies start with and the habit rules, `GET/PUT /api/pixie-settings` (D104)."""

import tomllib
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from tests.api_client import Api, running_api
from tests.fakes import FakeClock, FakeSecretStore

DEFAULTS = {
    "model": None,
    "autonomy": "observe",
    "project_access": "edit",
    "projects": "all",
    "max_running": 2,
    "max_per_day": 5,
    "report_push": "action",
    "habits_paused": False,
    "habit_usage_percent": 80,
}
CHOSEN = {
    **DEFAULTS,
    "model": "opus",
    "autonomy": "start",
    "project_access": "read",
    "max_running": 4,
    "max_per_day": 12,
    "report_push": "info",
}


@pytest.fixture
async def api(tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore) -> AsyncIterator[Api]:
    async with running_api(tmp_path, clock, secrets) as running:
        yield running


@pytest.mark.parametrize("method", ["GET", "PUT"])
async def test_routes_require_a_device_token(api: Api, method: str) -> None:
    response = await api.http.request(
        method, "/api/pixie-settings", headers={"Authorization": "Bearer wrong"}
    )

    assert response.status_code == 401


async def test_settings_round_trip_and_apply_at_once(api: Api) -> None:
    assert (await api.http.get("/api/pixie-settings")).json() == DEFAULTS

    saved = await api.http.put("/api/pixie-settings", json=CHOSEN)

    assert saved.status_code == 200
    assert saved.json() == CHOSEN
    assert api.ctx.settings.pixies.model == "opus"
    on_disk = tomllib.loads(api.ctx.paths.settings_file.read_text(encoding="utf-8"))
    assert on_disk["pixies"]["autonomy"] == "start"


@pytest.mark.parametrize(
    "change",
    [{"habit_usage_percent": 40}, {"report_push": "urgent"}, {"max_running": 0}, {"x": 1}],
)
async def test_invalid_settings_are_refused(api: Api, change: dict[str, object]) -> None:
    response = await api.http.put("/api/pixie-settings", json={**DEFAULTS, **change})

    assert response.status_code == 422


async def test_a_broken_settings_file_is_not_overwritten(api: Api) -> None:
    api.ctx.paths.settings_file.write_text("[pixies\n", encoding="utf-8")

    response = await api.http.put("/api/pixie-settings", json=CHOSEN)

    assert response.status_code == 409
    assert api.ctx.settings.pixies.model is None


async def test_new_pixies_start_with_the_settings_for_what_the_client_left_out(api: Api) -> None:
    await api.http.put("/api/pixie-settings", json=CHOSEN)

    filled = (await api.http.post("/api/pixies", json={"name": "Filled"})).json()
    chosen = (
        await api.http.post(
            "/api/pixies",
            json={"name": "Chosen", "model": None, "autonomy": "observe", "max_running": 1},
        )
    ).json()

    assert {key: filled[key] for key in CHOSEN if key in filled} == {
        "model": "opus",
        "autonomy": "start",
        "project_access": "read",
        "projects": None,
        "max_running": 4,
        "max_per_day": 12,
        "report_push": "info",
    }
    assert (chosen["model"], chosen["autonomy"], chosen["max_running"]) == (None, "observe", 1)
    assert (chosen["project_access"], chosen["max_per_day"]) == ("read", 12)
