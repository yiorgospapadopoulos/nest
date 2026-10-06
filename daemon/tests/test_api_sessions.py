from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from harness.events import types
from harness.storage.db import Database
from tests.api_client import Api, running_api
from tests.async_support import until
from tests.fake_provider import ask, hang, reply, until_interrupted
from tests.fakes import FakeClock, FakeSecretStore
from tests.git_support import init_repo


@pytest.fixture
async def api(tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore) -> AsyncIterator[Api]:
    async with running_api(tmp_path, clock, secrets) as running:
        await running.http.post("/api/repos", json={"path": str(init_repo(tmp_path / "repo"))})
        yield running


async def state_of(api: Api, session_id: str) -> str:
    return (await api.http.get(f"/api/sessions/{session_id}")).json()["state"]


async def reach(api: Api, session_id: str, state: str, results: int = 0) -> None:
    """Wait for the latest state event to be `state`, after at least `results` turn results."""

    async def reached() -> bool:
        events = (await api.http.get(f"/api/sessions/{session_id}/events")).json()
        states = [e["payload"]["state"] for e in events if e["type"] == types.SESSION_STATE]
        finished = [e for e in events if e["type"] == types.SESSION_RESULT]
        return bool(states) and states[-1] == state and len(finished) >= results

    await until(reached)


async def notified(api: Api, session_id: str, kind: str, count: int = 1) -> None:
    async def done() -> bool:
        events = (await api.http.get(f"/api/sessions/{session_id}/events")).json()
        kinds = [e["payload"]["kind"] for e in events if e["type"] == types.NOTIFY]
        return kinds.count(kind) >= count

    await until(done)


async def create(api: Api, **fields: object) -> dict[str, object]:
    response = await api.http.post(
        "/api/sessions", json={"repo": "repo", "prompt": "Do it", **fields}
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/sessions"),
        ("POST", "/api/sessions"),
        ("GET", "/api/sessions/x"),
        ("GET", "/api/sessions/x/events"),
        ("POST", "/api/sessions/x/messages"),
        ("POST", "/api/sessions/x/interrupt"),
        ("PATCH", "/api/sessions/x"),
        ("DELETE", "/api/sessions/x"),
    ],
)
async def test_session_routes_require_a_device_token(api: Api, method: str, path: str) -> None:
    response = await api.http.request(method, path, headers={"Authorization": "Bearer wrong"})

    assert response.status_code == 401


async def test_a_full_conversation(api: Api) -> None:
    api.provider.script(reply("first"), reply("second"))

    session = await create(api, model="claude-opus-5")
    await reach(api, str(session["id"]), "idle")
    sent = await api.http.post(f"/api/sessions/{session['id']}/messages", json={"text": "more"})
    await reach(api, str(session["id"]), "idle", results=2)
    await notified(api, str(session["id"]), "finished", 2)
    listed = await api.http.get("/api/sessions")
    events = await api.http.get(f"/api/sessions/{session['id']}/events")
    later = await api.http.get(
        f"/api/sessions/{session['id']}/events", params={"after": events.json()[-2]["id"]}
    )

    assert session["title"] == "Do it"
    assert session["model"] == "claude-opus-5"
    assert session["state"] == "starting"
    assert sent.status_code == 202
    assert [s["id"] for s in listed.json()] == [session["id"]]
    types_seen = [e["type"] for e in events.json()]
    assert types_seen.count(types.SESSION_RESULT) == 2
    assert types.SESSION_DELTA not in types_seen
    assert later.json() == events.json()[-1:]


async def test_permission_prompts_are_answered_through_the_approval_queue(api: Api) -> None:
    api.provider.script(ask("Bash", reply("done")))
    session = await create(api)
    session_id = str(session["id"])
    await reach(api, session_id, "waiting")
    (item,) = (await api.http.get("/api/approvals", params={"status": "pending"})).json()

    invalid = await api.http.post(
        f"/api/approvals/{item['id']}/resolve", json={"behavior": "maybe"}
    )
    answered = await api.http.post(
        f"/api/approvals/{item['id']}/resolve", json={"behavior": "deny", "message": "not that"}
    )
    await reach(api, session_id, "idle")

    assert item["kind"] == "permission"
    assert invalid.status_code == 422
    assert answered.status_code == 200
    assert answered.json()["status"] == "resolved"
    assert api.provider.runs[0].decisions[0].message == "not that"


async def test_interrupt_update_and_close(api: Api) -> None:
    api.provider.script(until_interrupted())
    session = await create(api)
    session_id = str(session["id"])
    await reach(api, session_id, "running")
    await until(lambda: bool(api.provider.runs) and bool(api.provider.runs[0].inputs))

    busy = await api.http.post(f"/api/sessions/{session_id}/messages", json={"text": "x"})
    patched = await api.http.patch(f"/api/sessions/{session_id}", json={"permission_mode": "plan"})
    interrupted = await api.http.post(f"/api/sessions/{session_id}/interrupt")
    await reach(api, session_id, "interrupted")
    idle_interrupt = await api.http.post(f"/api/sessions/{session_id}/interrupt")
    closed = await api.http.delete(f"/api/sessions/{session_id}", params={"remove_worktree": True})
    again = await api.http.delete(f"/api/sessions/{session_id}")

    assert busy.status_code == 409
    assert "busy" in busy.json()["detail"]
    assert patched.json()["permission_mode"] == "plan"
    assert api.provider.runs[0].calls[0] == ("set_permission_mode", "plan")
    assert interrupted.status_code == 202
    assert idle_interrupt.status_code == 409
    assert closed.status_code == 200
    assert closed.json()["state"] == "closed"
    assert again.status_code == 409


async def test_dirty_in_place_sessions_report_the_files(api: Api, tmp_path: Path) -> None:
    (tmp_path / "repo" / "README.md").write_text("changed", encoding="utf-8")

    response = await api.http.post(
        "/api/sessions", json={"repo": "repo", "prompt": "x", "mode": "in_place"}
    )

    assert response.status_code == 409
    assert response.json()["files"] == ["README.md"]


@pytest.mark.parametrize(
    ("body", "status"),
    [
        ({"repo": "nope", "prompt": "x"}, 422),
        ({"repo": "repo", "prompt": "   "}, 422),
        ({"repo": "repo", "prompt": "x", "mode": "elsewhere"}, 422),
        ({"repo": "repo", "prompt": "x", "attachment_ids": ["missing"]}, 422),
        ({"repo": "repo", "prompt": "x", "surprise": 1}, 422),
    ],
)
async def test_create_validation(api: Api, body: dict[str, object], status: int) -> None:
    assert (await api.http.post("/api/sessions", json=body)).status_code == status


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", "/api/sessions/nope", None),
        ("GET", "/api/sessions/nope/events", None),
        ("POST", "/api/sessions/nope/messages", {"text": "x"}),
        ("POST", "/api/sessions/nope/interrupt", None),
        ("PATCH", "/api/sessions/nope", {}),
        ("DELETE", "/api/sessions/nope", None),
    ],
)
async def test_unknown_sessions_are_404(
    api: Api, method: str, path: str, body: dict[str, object] | None
) -> None:
    response = await api.http.request(method, path, json=body)

    assert response.status_code == 404
    assert response.json() == {"detail": "unknown session 'nope'"}


async def test_events_reject_a_negative_after(api: Api) -> None:
    api.provider.script(reply("ok"))
    session = await create(api)

    response = await api.http.get(f"/api/sessions/{session['id']}/events", params={"after": -1})

    assert response.status_code == 422


@pytest.mark.parametrize("killed_in", ["running", "waiting", "starting"])
async def test_restart_interrupts_running_sessions_and_resume_works(
    tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore, killed_in: str
) -> None:
    async with running_api(tmp_path, clock, secrets) as first:
        await first.http.post("/api/repos", json={"path": str(init_repo(tmp_path / "repo"))})
        first.provider.script(reply("one", "sdk-9"))
        session_id = str((await create(first))["id"])
        await reach(first, session_id, "idle")
        db_path = first.ctx.paths.db_path
    # As if the daemon had died mid-turn.
    db = await Database.open(db_path)
    await db.execute("UPDATE sessions SET state = ? WHERE id = ?", (killed_in, session_id))
    await db.close()

    async with running_api(tmp_path, clock, secrets) as second:
        recovered = await state_of(second, session_id)
        second.provider.script(reply("resumed"))
        resumed = await second.http.post(
            f"/api/sessions/{session_id}/messages", json={"text": "go on"}
        )
        await reach(second, session_id, "idle")

    assert recovered == "interrupted"
    assert resumed.status_code == 202
    assert second.provider.runs[0].spec.resume_id == "sdk-9"


async def test_shutdown_interrupts_a_running_turn(
    tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore
) -> None:
    async with running_api(tmp_path, clock, secrets) as api:
        await api.http.post("/api/repos", json={"path": str(init_repo(tmp_path / "repo"))})
        api.provider.script(hang())
        session_id = str((await create(api))["id"])
        await until(lambda: bool(api.provider.runs) and bool(api.provider.runs[0].inputs))

    async with running_api(tmp_path, clock, secrets) as restarted:
        assert await state_of(restarted, session_id) == "interrupted"
    assert api.provider.runs[0].closed is True
