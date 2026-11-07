"""`/api/updates`: device auth, and Relaunch and Undo refuse when there is nothing to do."""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from nestd.providers.shell_env import no_shell_env
from nestd.updates.service import UpdateService, UpdateSetup
from nestd.updates.state import BASE, StateFile, UpdateState
from tests.api_client import Api, running_api
from tests.fakes import FakeClock, FakeSecretStore
from tests.updates_support import FINGERPRINT, NOW, SAME, make_environment, registry


@pytest.fixture
async def api(tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore) -> AsyncIterator[Api]:
    async with running_api(tmp_path, clock, secrets) as running:
        running.ctx.updates = UpdateService(
            paths=running.ctx.paths,
            platform="macos",
            bus=running.ctx.bus,
            shell_env=no_shell_env,
            busy_chats=lambda: 2,
            port=lambda: 41010,
            setup=UpdateSetup(transport=registry(SAME), versions=lambda: NOW),
        )
        yield running


def files(api: Api) -> StateFile:
    return StateFile(api.ctx.paths.environments_dir)


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/updates"),
        ("POST", "/api/updates/check"),
        ("POST", "/api/updates/relaunch"),
        ("POST", "/api/updates/undo"),
        ("POST", "/api/updates/dismiss"),
    ],
)
async def test_every_route_needs_a_device_token(api: Api, method: str, path: str) -> None:
    response = await api.http.request(method, path, headers={"Authorization": "Bearer wrong"})

    assert response.status_code == 401
    assert api.restart.calls == 0


async def test_the_status_says_what_a_client_needs(api: Api) -> None:
    files(api).save(UpdateState(previous=BASE, current="aaaaaaaaaaaa", notice="It went back."))

    response = await api.http.get("/api/updates")

    assert response.status_code == 200
    assert response.json() == {
        "state": "none",
        "engines": [],
        "app": None,
        "app_file": None,
        "busy_chats": 2,
        "can_undo": True,
        "notice": "It went back.",
    }


async def test_a_check_answers_at_once(api: Api) -> None:
    response = await api.http.post("/api/updates/check")

    assert response.status_code == 202
    assert response.json()["state"] == "checking"
    await api.ctx.updates.stop_when_done()


async def test_relaunch_without_an_update_is_refused(api: Api) -> None:
    response = await api.http.post("/api/updates/relaunch")

    assert response.status_code == 409
    assert api.restart.calls == 0


async def test_relaunch_swaps_and_restarts_the_daemon(api: Api) -> None:
    root = api.ctx.paths.environments_dir
    root.mkdir()
    make_environment(root, "aaaaaaaaaaaa", packages={**NOW.packages, "claude": "0.3.0"})
    files(api).save(UpdateState(ready="aaaaaaaaaaaa", base_fingerprint=FINGERPRINT))

    status = await api.http.get("/api/updates")
    response = await api.http.post("/api/updates/relaunch")

    assert status.json()["state"] == "ready"
    assert status.json()["engines"][0]["id"] == "claude"
    assert response.status_code == 202
    assert response.json() == {"restarting": True}
    assert api.restart.calls == 1
    state = files(api).load()
    assert (state.current, state.previous, state.trial) == ("aaaaaaaaaaaa", BASE, True)


async def test_undo_with_nothing_to_go_back_to_is_refused(api: Api) -> None:
    response = await api.http.post("/api/updates/undo")

    assert response.status_code == 409
    assert api.restart.calls == 0


async def test_undo_goes_back_and_restarts_the_daemon(api: Api) -> None:
    files(api).save(UpdateState(current="aaaaaaaaaaaa", previous=BASE))

    response = await api.http.post("/api/updates/undo")

    assert response.status_code == 202
    assert api.restart.calls == 1
    assert files(api).load().current is None


async def test_dismiss_clears_the_notice(api: Api) -> None:
    files(api).save(UpdateState(notice="It went back."))

    response = await api.http.post("/api/updates/dismiss")

    assert response.status_code == 200
    assert response.json()["notice"] is None
    assert files(api).load().notice is None
