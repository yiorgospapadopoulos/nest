from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path

import pytest

from nestd.events import types
from tests.api_client import Api, running_api
from tests.async_support import until
from tests.fake_provider import reply, until_interrupted
from tests.fakes import FakeClock, FakeSecretStore
from tests.git_support import init_repo
from tests.test_api_sessions import create, notified, reach


@pytest.fixture
async def api(tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore) -> AsyncIterator[Api]:
    async with running_api(tmp_path, clock, secrets) as running:
        await running.http.post("/api/repos", json={"path": str(init_repo(tmp_path / "repo"))})
        yield running


@pytest.mark.parametrize(
    ("method", "path"), [("GET", "/api/stuck/settings"), ("PUT", "/api/stuck/settings")]
)
async def test_stuck_settings_require_a_device_token(api: Api, method: str, path: str) -> None:
    response = await api.http.request(method, path, headers={"Authorization": "Bearer wrong"})

    assert response.status_code == 401


async def test_stuck_settings_can_be_read_and_replaced(api: Api) -> None:
    defaults = (await api.http.get("/api/stuck/settings")).json()
    saved = await api.http.put("/api/stuck/settings", json={**defaults, "silent_minutes": 3})
    bad = await api.http.put("/api/stuck/settings", json={"silent_minutes": -1})
    api.ctx.paths.settings_file.write_text("[stuck\n", encoding="utf-8")
    broken = await api.http.put("/api/stuck/settings", json=defaults)

    assert defaults == {
        "waiting_minutes": 15,
        "silent_minutes": 10,
        "repeated_calls": 4,
        "turn_minutes": 60,
    }
    assert saved.status_code == 200
    assert api.ctx.settings.stuck.silent_minutes == 3
    assert bad.status_code == 422
    assert broken.status_code == 409


async def test_a_silent_session_is_flagged_and_a_nudge_gets_it_going(
    api: Api, clock: FakeClock
) -> None:
    api.provider.script(until_interrupted(), reply("Trying something else."))
    session = await create(api, prompt="Long job")
    session_id = str(session["id"])
    await reach(api, session_id, "running")
    await until(lambda: bool(api.provider.runs) and bool(api.provider.runs[0].inputs))

    clock.advance(timedelta(minutes=10))

    async def flagged() -> bool:
        # The watcher follows events in its own task; check again until it saw the turn.
        await api.ctx.stuck.tick()
        return (await api.http.get(f"/api/sessions/{session_id}")).json()["stuck"] is not None

    await until(flagged)
    detail = (await api.http.get(f"/api/sessions/{session_id}")).json()
    listed = (await api.http.get("/api/sessions")).json()
    assert detail["stuck"] == {
        "reason": "silent",
        "since": detail["stuck"]["since"],
        "details": "No new output for 10 minutes",
    }
    assert listed[0]["stuck"] == detail["stuck"]
    await notified(api, session_id, "stuck")

    nudge = "You seem stuck: no new output for 10 minutes. Step back and try a different approach."
    sent = await api.http.post(
        f"/api/sessions/{session_id}/messages", json={"text": nudge, "interrupt": True}
    )
    assert sent.status_code == 202
    assert sent.json()["queued_message"]["text"] == nudge
    await reach(api, session_id, "idle", results=2)

    events = (await api.http.get(f"/api/sessions/{session_id}/events")).json()
    kinds = [e["type"] for e in events]
    assert types.SESSION_UNSTUCK in kinds
    assert (await api.http.get(f"/api/sessions/{session_id}")).json()["stuck"] is None
    texts = [e["payload"]["text"] for e in events if e["type"] == types.SESSION_USER_MESSAGE]
    assert texts == ["Long job", nudge]
