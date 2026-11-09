"""Computer use through the API (B150): Settings saved to the file, and a chat's next run
gets the tools only once both its switch and Settings are on."""

import tomllib
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from nestd.paths import AppPaths
from tests.api_client import Api, running_api
from tests.async_support import until
from tests.fake_provider import reply
from tests.fakes import FakeClock, FakeSecretStore
from tests.git_support import init_repo
from tests.test_api_sessions import create, reach


@pytest.fixture
async def api(tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore) -> AsyncIterator[Api]:
    async with running_api(tmp_path, clock, secrets) as running:
        await running.http.post("/api/repos", json={"path": str(init_repo(tmp_path / "repo"))})
        yield running


def computer_tools(api: Api, run: int) -> list[str]:
    return [
        t.name for t in api.provider.runs[run].spec.nest_tools if t.name.startswith("computer_")
    ]


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/computer/settings"),
        ("POST", "/api/sessions/x/computer/stop"),
        ("GET", "/api/sessions/x/computer/frame"),
    ],
)
async def test_it_requires_a_device_token(api: Api, method: str, path: str) -> None:
    response = await api.http.request(method, path, headers={"Authorization": "Bearer wrong"})

    assert response.status_code == 401


async def test_settings_start_off_and_are_saved(api: Api, tmp_path: Path) -> None:
    assert (await api.http.get("/api/computer/settings")).json() == {
        "enabled": False,
        "pixies": False,
    }

    body = {"enabled": True, "pixies": True}
    saved = await api.http.put("/api/computer/settings", json=body)

    assert saved.json() == body
    paths = AppPaths(config_dir=tmp_path / "config", data_dir=tmp_path / "data")
    written = tomllib.loads(paths.settings_file.read_text(encoding="utf-8"))
    assert written["computer_use"] == body


async def test_a_chats_next_run_gets_the_tools_once_settings_has_it_on(api: Api) -> None:
    api.provider.script(reply("one"), reply("two"))
    session = await create(api)
    session_id = str(session["id"])
    await reach(api, session_id, "idle")
    assert computer_tools(api, 0) == []

    settings: dict[str, object] = {"enabled": True, "pixies": False}
    # Settings going on reaches a chat whose run is open already.
    await api.http.put("/api/computer/settings", json=settings)
    await api.http.post(f"/api/sessions/{session_id}/messages", json={"text": "again"})
    await reach(api, session_id, "idle", results=2)
    await until(lambda: bool(computer_tools(api, -1)))

    assert computer_tools(api, -1) == [
        "computer_targets",
        "computer_open",
        "computer_view",
        "computer_act",
        "computer_release",
    ]
    assert (await api.http.get(f"/api/sessions/{session_id}/computer/frame")).status_code == 404
