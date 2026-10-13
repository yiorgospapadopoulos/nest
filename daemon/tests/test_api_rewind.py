"""IMP-02: `GET` and `POST /api/sessions/{id}/rewind`."""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from harness.events import types
from harness.providers.base import RewindResult
from tests.api_client import Api, running_api
from tests.async_support import until
from tests.fake_provider import echoed, hang, reply
from tests.fakes import FakeClock, FakeSecretStore
from tests.git_support import init_repo
from tests.test_api_sessions import create, reach


@pytest.fixture
async def api(tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore) -> AsyncIterator[Api]:
    async with running_api(tmp_path, clock, secrets) as running:
        await running.http.post("/api/repos", json={"path": str(init_repo(tmp_path / "repo"))})
        yield running


async def first_message(api: Api, session_id: str) -> int:
    events = (await api.http.get(f"/api/sessions/{session_id}/events")).json()
    return next(e["id"] for e in events if e["type"] == types.SESSION_USER_MESSAGE)


@pytest.mark.parametrize(
    ("method", "path"),
    [("GET", "/api/sessions/s/rewind?message=1"), ("POST", "/api/sessions/s/rewind")],
)
async def test_rewind_routes_require_a_device_token(api: Api, method: str, path: str) -> None:
    response = await api.http.request(method, path, headers={"Authorization": "Bearer wrong"})

    assert response.status_code == 401


async def test_a_preview_then_a_restore(api: Api) -> None:
    api.provider.script(echoed("msg-1", reply("done")))
    api.provider.rewind = RewindResult(
        can_rewind=True, files_changed=["a.py", "b.py"], insertions=4, deletions=2
    )
    session_id = str((await create(api))["id"])
    await reach(api, session_id, "idle")
    message = await first_message(api, session_id)
    url = f"/api/sessions/{session_id}/rewind"

    preview = await api.http.get(url, params={"message": message})
    restored = await api.http.post(url, json={"message": message})

    expected = {
        "can_rewind": True,
        "files_changed": ["a.py", "b.py"],
        "insertions": 4,
        "deletions": 2,
        "error": None,
    }
    assert (preview.status_code, preview.json()) == (200, expected)
    assert (restored.status_code, restored.json()) == (200, expected)
    events = (await api.http.get(f"/api/sessions/{session_id}/events")).json()
    assert [e["payload"] for e in events if e["type"] == types.SESSION_NOTICE] == [
        {"kind": "files_restored", "text": "Restored 2 files to before your message"}
    ]


async def test_a_message_without_a_checkpoint(api: Api) -> None:
    api.provider.script(reply("done"))
    session_id = str((await create(api))["id"])
    await reach(api, session_id, "idle")
    message = await first_message(api, session_id)
    url = f"/api/sessions/{session_id}/rewind"

    preview = await api.http.get(url, params={"message": message})
    restored = await api.http.post(url, json={"message": message})

    assert preview.status_code == 200
    assert preview.json()["can_rewind"] is False
    assert restored.status_code == 409
    assert restored.json()["code"] == "cannot_rewind"
    assert "no file checkpoint" in restored.json()["detail"]


async def test_restoring_while_the_agent_works_is_refused(api: Api) -> None:
    api.provider.script(echoed("msg-1", hang()))
    session_id = str((await create(api))["id"])
    await reach(api, session_id, "running")
    message = await first_message(api, session_id)

    async def refused() -> bool:
        # Once the engine's echo gave the message its checkpoint.
        response = await api.http.post(
            f"/api/sessions/{session_id}/rewind", json={"message": message}
        )
        return response.status_code == 409 and "idle" in response.json()["detail"]

    await until(refused)


@pytest.mark.parametrize(
    ("method", "kwargs"),
    [
        ("GET", {}),
        ("GET", {"params": {"message": 0}}),
        ("POST", {"json": {}}),
        ("POST", {"json": {"message": 1, "extra": True}}),
    ],
)
async def test_the_message_is_required(api: Api, method: str, kwargs: dict[str, object]) -> None:
    api.provider.script(reply("done"))
    session_id = str((await create(api))["id"])

    response = await api.http.request(
        method,
        f"/api/sessions/{session_id}/rewind",
        **kwargs,  # pyright: ignore[reportArgumentType]
    )

    assert response.status_code == 422


async def test_an_unknown_session(api: Api) -> None:
    response = await api.http.get("/api/sessions/nope/rewind", params={"message": 1})

    assert response.status_code == 404
