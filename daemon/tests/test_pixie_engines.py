"""B91 stage 2: a pixie runs on Claude (the default) or Codex, its chats and habit runs on
that engine, with its Nest tools served to Codex as a local MCP server.
"""

import shutil
from collections.abc import AsyncIterator
from pathlib import Path
from typing import cast

import pytest

from nestd.providers.codex_engine import NOT_SIGNED_IN
from nestd.providers.codex_rpc import JsonObject
from nestd.providers.codex_tools import TOKEN_ENV
from nestd.storage.db import Database
from nestd.storage.migrations import PACKAGED
from tests.api_client import Api, running_api
from tests.async_support import until
from tests.codex_support import SIGNED_OUT, turn_completed
from tests.fake_provider import reply
from tests.fakes import FakeClock, FakeSecretStore
from tests.test_api_sessions import reach


@pytest.fixture
async def api(tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore) -> AsyncIterator[Api]:
    async with running_api(tmp_path, clock, secrets) as running:
        yield running


async def test_earlier_pixies_are_claudes_and_no_chat_is_a_call(tmp_path: Path) -> None:
    before = tmp_path / "before"
    before.mkdir()
    for entry in PACKAGED.iterdir():
        if entry.name.endswith(".sql") and entry.name < "0035":
            (before / entry.name).write_text(entry.read_text(encoding="utf-8"), encoding="utf-8")
    path = tmp_path / "nest.db"
    old = await Database.open(path, before)
    await old.execute(
        "INSERT INTO pixies (id, name, slug, position, mascot, color, model, effort,"
        " permission_mode, autonomy, project_access, skills, can_call, hidden, max_running,"
        " max_per_day, created_at, updated_at) VALUES ('p1', 'Old', 'old', 0, 'invader',"
        " '#8B7CF6', NULL, NULL, 'default', 'observe', 'edit', '[]', '[]', 0, 2, 5,"
        " '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')"
    )
    await old.close()
    shutil.rmtree(before)

    db = await Database.open(path)
    try:
        pixie = await db.fetch_one("SELECT provider FROM pixies")
        columns = {row["name"] for row in await db.fetch_all("PRAGMA table_info(sessions)")}
    finally:
        await db.close()

    assert pixie is not None
    assert pixie["provider"] == "claude"
    assert "called_by" in columns


async def test_a_pixie_runs_on_claude_unless_set_to_codex(api: Api) -> None:
    plain = await api.http.post("/api/pixies", json={"name": "Plain"})
    coder = await api.http.post(
        "/api/pixies",
        json={"name": "Coder", "provider": "codex", "model": "gpt-5.5", "effort": "high"},
    )
    unknown = await api.http.post("/api/pixies", json={"name": "G", "provider": "gemini"})

    assert plain.json()["provider"] == "claude"
    assert coder.status_code == 201, coder.text
    assert (coder.json()["provider"], coder.json()["model"]) == ("codex", "gpt-5.5")
    assert unknown.status_code == 422
    assert "unknown provider" in unknown.json()["detail"]
    listed = (await api.http.get("/api/pixies")).json()
    assert [p["provider"] for p in listed] == ["claude", "codex"]


async def test_a_codex_pixie_takes_no_claude_model_default(api: Api) -> None:
    defaults = (await api.http.get("/api/pixie-settings")).json()
    saved = await api.http.put("/api/pixie-settings", json={**defaults, "model": "opus"})
    assert saved.status_code == 200, saved.text

    claude = (await api.http.post("/api/pixies", json={"name": "C"})).json()
    codex = (await api.http.post("/api/pixies", json={"name": "X", "provider": "codex"})).json()

    assert claude["model"] == "opus"
    assert codex["model"] is None


async def test_moving_a_pixie_to_another_engine_starts_its_chat_afresh(api: Api) -> None:
    api.provider.script(reply("hi"))
    pid = (
        await api.http.post("/api/pixies", json={"name": "P", "model": "opus", "effort": "high"})
    ).json()["id"]
    chat = (await api.http.post(f"/api/pixies/{pid}/messages", json={"text": "hi"})).json()
    await reach(api, chat["id"], "idle", results=1)

    moved = await api.http.patch(f"/api/pixies/{pid}", json={"provider": "codex"})
    with_model = await api.http.patch(
        f"/api/pixies/{pid}", json={"provider": "codex", "model": "gpt-5.5"}
    )
    old_chat = (await api.http.get(f"/api/sessions/{chat['id']}")).json()

    assert moved.status_code == 200, moved.text
    assert (moved.json()["provider"], moved.json()["model"], moved.json()["effort"]) == (
        "codex",
        None,
        None,
    )
    assert moved.json()["chat_session_id"] is None
    assert old_chat["archived_at"] is not None
    assert with_model.json()["model"] == "gpt-5.5"


async def test_a_codex_pixies_chat_runs_on_codex_with_its_tools(api: Api) -> None:
    api.codex.script(turn_completed())
    pid = (
        await api.http.post(
            "/api/pixies",
            json={"name": "Coder", "provider": "codex", "model": "gpt-5.5", "autonomy": "start"},
        )
    ).json()["id"]

    sent = await api.http.post(f"/api/pixies/{pid}/messages", json={"text": "hello"})
    chat_id = sent.json()["id"]
    await reach(api, chat_id, "idle", results=1)

    assert sent.status_code == 202, sent.text
    assert (sent.json()["provider"], sent.json()["model"]) == ("codex", "gpt-5.5")
    assert api.provider.runs == []
    [start] = api.codex.requests("thread/start")
    config = cast("JsonObject", start["config"])
    # Its memory, habit and Nest tools, and the artifact tools every run has.
    assert {"mcp_servers.pixie", "mcp_servers.nest"} <= set(config)
    assert "shell_environment_policy.set" in config
    [run_launch] = [launch for launch in api.codex.launches if launch.cwd is not None]
    assert TOKEN_ENV in run_launch.env
    assert "Coder" in str(start["developerInstructions"])
    [turn] = api.codex.requests("turn/start")
    assert turn["model"] == "gpt-5.5"
    # A pixie's run is guarded: Codex asks before every command, without network.
    assert turn["approvalPolicy"] == "untrusted"
    assert cast("JsonObject", turn["sandboxPolicy"])["networkAccess"] is False


async def test_a_codex_pixie_while_codex_is_signed_out_is_refused(api: Api) -> None:
    api.codex.answers["account/read"] = SIGNED_OUT
    pid = (await api.http.post("/api/pixies", json={"name": "X", "provider": "codex"})).json()["id"]

    sent = await api.http.post(f"/api/pixies/{pid}/messages", json={"text": "hello"})

    assert sent.status_code == 409
    assert sent.json() == {"detail": NOT_SIGNED_IN, "code": "codex_not_signed_in"}


async def test_a_codex_pixies_habit_runs_on_codex(api: Api) -> None:
    api.codex.script(turn_completed())
    pid = (await api.http.post("/api/pixies", json={"name": "Coder", "provider": "codex"})).json()[
        "id"
    ]
    habit = {
        "name": "Check",
        "prompt": "Look around.",
        "schedule": {"kind": "daily", "time": "09:00"},
    }
    hid = (await api.http.post(f"/api/pixies/{pid}/habits", json=habit)).json()["id"]

    await api.http.post(f"/api/pixies/{pid}/habits/{hid}/run")

    async def done() -> bool:
        runs = (await api.http.get(f"/api/pixies/{pid}/habits/{hid}/runs")).json()
        return [r["outcome"] for r in runs] == ["quiet"]

    await until(done)
    [run] = (await api.http.get(f"/api/pixies/{pid}/habits/{hid}/runs")).json()
    session = (await api.http.get(f"/api/sessions/{run['session_id']}")).json()
    assert session["provider"] == "codex"
    assert api.provider.runs == []
    [start] = api.codex.requests("thread/start")
    assert "mcp_servers.pixie" in cast("JsonObject", start["config"])


async def test_a_codex_pixie_takes_no_skill_list_but_keeps_a_stored_one(api: Api) -> None:
    refusal = {
        "detail": "A Codex pixie cannot be limited to chosen skills.",
        "code": "unsupported_feature",
        "provider": "codex",
        "feature": "pixie_skills",
    }
    created = await api.http.post(
        "/api/pixies", json={"name": "X", "provider": "codex", "skills": ["review"]}
    )
    claude = (await api.http.post("/api/pixies", json={"name": "C", "skills": ["review"]})).json()
    moved = await api.http.patch(f"/api/pixies/{claude['id']}", json={"provider": "codex"})
    set_skills = await api.http.patch(
        f"/api/pixies/{claude['id']}", json={"skills": ["review", "debug"]}
    )
    moving_with_skills = await api.http.post("/api/pixies", json={"name": "Y"})
    both = await api.http.patch(
        f"/api/pixies/{moving_with_skills.json()['id']}",
        json={"provider": "codex", "skills": ["review"]},
    )
    cleared = await api.http.patch(f"/api/pixies/{claude['id']}", json={"skills": []})

    assert (created.status_code, created.json()) == (409, refusal)
    # Moved to Codex, its list stays stored, unused, until it is back on Claude.
    assert moved.status_code == 200
    assert moved.json()["skills"] == ["review"]
    assert (set_skills.status_code, set_skills.json()) == (409, refusal)
    assert both.status_code == 409
    assert (await api.http.get(f"/api/pixies/{moving_with_skills.json()['id']}")).json()[
        "provider"
    ] == "claude"
    # Clearing it changes nothing a run uses, so it is allowed.
    assert cleared.status_code == 200
    assert cleared.json()["skills"] == []
    providers = (await api.http.get("/api/providers")).json()["providers"]
    assert "pixie_skills" in providers[1]["unsupported"]
    assert "pixie_skills" not in providers[0]["unsupported"]
