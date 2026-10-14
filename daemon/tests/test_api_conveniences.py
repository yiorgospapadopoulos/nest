"""The API of B24: slash commands, file mentions, plans, context and queued messages."""

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from nestd.providers.base import (
    AgentInfo,
    CommandCatalog,
    ContextUsage,
    SlashCommand,
)
from nestd.storage.db import Database
from tests.api_client import Api, running_api
from tests.async_support import until
from tests.fake_provider import FakeRun, catalog, plan, reply
from tests.fakes import FakeClock, FakeSecretStore
from tests.git_support import init_repo
from tests.test_api_sessions import create, reach


@pytest.fixture
async def api(tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore) -> AsyncIterator[Api]:
    async with running_api(tmp_path, clock, secrets) as running:
        await running.http.post("/api/repos", json={"path": str(init_repo(tmp_path / "repo"))})
        yield running


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/sessions/x/commands"),
        ("GET", "/api/sessions/x/files"),
        ("DELETE", "/api/sessions/x/queue/q"),
        ("GET", "/api/repos/repo/commands"),
    ],
)
async def test_routes_require_a_device_token(api: Api, method: str, path: str) -> None:
    response = await api.http.request(method, path, headers={"Authorization": "Bearer wrong"})

    assert response.status_code == 401


async def test_commands_of_a_session_and_of_its_repo(api: Api) -> None:
    before = await api.http.get("/api/repos/repo/commands")
    reported = CommandCatalog(
        commands=[SlashCommand(name="compact", description="Compact", argument_hint="[note]")],
        agents=[AgentInfo(name="Plan")],
    )
    api.provider.script(catalog(reported, reply("ok")))
    session = await create(api)
    await reach(api, str(session["id"]), "idle")

    own = await api.http.get(f"/api/sessions/{session['id']}/commands")
    repo = await api.http.get("/api/repos/repo/commands")
    unknown_repo = await api.http.get("/api/repos/nope/commands")
    unknown_session = await api.http.get("/api/sessions/nope/commands")

    assert before.json() == {"source": "none", "commands": [], "agents": [], "updated_at": None}
    assert own.json()["source"] == "session"
    assert own.json()["commands"] == [
        {"name": "compact", "description": "Compact", "argument_hint": "[note]"}
    ]
    assert own.json()["agents"] == [{"name": "Plan", "description": None}]
    assert repo.json()["source"] == "repo"
    assert unknown_repo.status_code == 404
    assert unknown_session.status_code == 404


async def test_file_suggestions(api: Api, tmp_path: Path) -> None:
    api.provider.script(reply("ok"))
    session = await create(api, mode="in_place")
    await reach(api, str(session["id"]), "idle")
    (tmp_path / "repo" / "src").mkdir()
    (tmp_path / "repo" / "src" / "main.py").write_text("x", encoding="utf-8")

    found = await api.http.get(f"/api/sessions/{session['id']}/files", params={"q": "main"})
    everything = await api.http.get(f"/api/sessions/{session['id']}/files")
    too_long = await api.http.get(f"/api/sessions/{session['id']}/files", params={"q": "x" * 201})

    assert found.json() == {"files": ["src/main.py"]}
    assert everything.json() == {"files": ["README.md", "src/main.py"]}
    assert too_long.status_code == 422


async def test_plans_are_approved_through_the_approval_queue(api: Api) -> None:
    api.provider.script(plan("# Plan", reply("building")))
    session = await create(api, permission_mode="plan")
    session_id = str(session["id"])
    await reach(api, session_id, "waiting")
    (item,) = (await api.http.get("/api/approvals", params={"status": "pending"})).json()

    wrong = await api.http.post(f"/api/approvals/{item['id']}/resolve", json={"behavior": "allow"})
    approved = await api.http.post(
        f"/api/approvals/{item['id']}/resolve", json={"decision": "approve"}
    )
    await reach(api, session_id, "idle")
    detail = await api.http.get(f"/api/sessions/{session_id}")

    assert item["kind"] == "plan"
    assert item["payload"] == {"plan": "# Plan", "tool_use_id": "toolu_plan"}
    assert wrong.status_code == 422
    assert approved.json()["resolution"] == {"decision": "approve", "mode": "acceptEdits"}
    assert detail.json()["permission_mode"] == "acceptEdits"


async def test_messages_during_a_turn_are_queued_shown_and_cancellable(api: Api) -> None:
    gate = asyncio.Event()

    async def slow(run: FakeRun) -> None:
        await gate.wait()
        await reply("first")(run)

    api.provider.context = ContextUsage(percent=12.5, used=25000, limit=200000)
    api.provider.script(slow, reply("kept"))
    session = await create(api)
    session_id = str(session["id"])
    await reach(api, session_id, "running")

    kept = await api.http.post(f"/api/sessions/{session_id}/messages", json={"text": "keep me"})
    dropped = await api.http.post(f"/api/sessions/{session_id}/messages", json={"text": "drop me"})
    dropped_id = dropped.json()["queued_message"]["id"]
    cancelled = await api.http.delete(f"/api/sessions/{session_id}/queue/{dropped_id}")
    again = await api.http.delete(f"/api/sessions/{session_id}/queue/{dropped_id}")
    waiting = (await api.http.get(f"/api/sessions/{session_id}")).json()["queued"]
    gate.set()
    await reach(api, session_id, "idle", results=2)
    detail = (await api.http.get(f"/api/sessions/{session_id}")).json()
    events = (await api.http.get(f"/api/sessions/{session_id}/events")).json()

    assert kept.status_code == 202
    assert kept.json()["state"] == "running"
    assert kept.json()["queued_message"]["text"] == "keep me"
    assert kept.json()["queued_message"]["attachments"] == []
    assert cancelled.status_code == 204
    assert again.status_code == 404
    assert [m["text"] for m in waiting] == ["keep me"]
    assert detail["queued"] == []
    assert detail["context"] == {"percent": 12.5, "used": 25000, "limit": 200000}
    texts = [e["payload"]["text"] for e in events if e["type"] == "session.user_message"]
    assert texts == ["Do it", "keep me"]
    assert [e["payload"]["queued"] for e in events if e["type"] == "session.queued"][-1] == []
    assert any(e["type"] == "session.context" for e in events)


async def test_an_idle_send_starts_at_once(api: Api) -> None:
    api.provider.script(reply("one"), reply("two"))
    session = await create(api)
    await reach(api, str(session["id"]), "idle")

    sent = await api.http.post(f"/api/sessions/{session['id']}/messages", json={"text": "now"})
    await until(lambda: len(api.provider.runs[0].inputs) == 2)

    assert sent.json()["queued_message"] is None


async def test_the_approvals_table_accepts_plans(db: Database) -> None:
    row = await db.fetch_one(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'approvals'"
    )

    assert row is not None
    assert "'plan'" in row["sql"]
