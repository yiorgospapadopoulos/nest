from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from tests.api_client import Api, running_api
from tests.fakes import FakeClock, FakeSecretStore


@pytest.fixture
async def api(tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore) -> AsyncIterator[Api]:
    async with running_api(tmp_path, clock, secrets) as running:
        yield running


async def test_restart_needs_a_device_token(api: Api) -> None:
    response = await api.http.post(
        "/api/service/restart", headers={"Authorization": "Bearer wrong"}
    )

    assert response.status_code == 401
    assert api.restart.calls == 0


async def test_restart_answers_then_ends_the_daemon_once(api: Api) -> None:
    response = await api.http.post("/api/service/restart")

    assert response.status_code == 202
    assert response.json() == {"restarting": True}
    assert api.restart.calls == 1
