import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from nestd.events import types
from tests.api_client import Api, running_api
from tests.async_support import until
from tests.fake_engine import server_info
from tests.fake_provider import FakeRun, edit, reply
from tests.fakes import FakeClock, FakeSecretStore
from tests.git_support import git
from tests.test_api_sessions import notified, reach


@pytest.fixture
async def api(tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore) -> AsyncIterator[Api]:
    async with running_api(tmp_path, clock, secrets) as running:
        yield running


@pytest.mark.parametrize(
    ("method", "path"),
    [("GET", "/api/pixies"), ("POST", "/api/pixies"), ("GET", "/api/pixies/x/files/soul")],
)
async def test_pixies_need_a_device_token(api: Api, method: str, path: str) -> None:
    response = await api.http.request(method, path, headers={"Authorization": "Bearer wrong"})

    assert response.status_code == 401


async def test_crud(api: Api) -> None:
    created = await api.http.post("/api/pixies", json={"name": "Tester", "color": "#112233"})
    pid = created.json()["id"]
    listed = await api.http.get("/api/pixies")
    patched = await api.http.patch(f"/api/pixies/{pid}", json={"mascot": "ghost"})
    bad = await api.http.post("/api/pixies", json={"name": "P", "slug": "plan"})
    taken = await api.http.post("/api/pixies", json={"name": "X", "slug": "tester"})
    unknown = await api.http.get("/api/pixies/nope")
    deleted = await api.http.delete(f"/api/pixies/{pid}")

    assert created.status_code == 201
    assert created.json()["slug"] == "tester"
    assert [p["id"] for p in listed.json()] == [pid]
    assert patched.json()["mascot"] == "ghost"
    assert bad.status_code == 422
    assert taken.status_code == 409
    assert unknown.status_code == 404
    assert deleted.status_code == 204


async def test_messages_and_reset(api: Api) -> None:
    api.provider.script(reply("hi"))
    pid = (await api.http.post("/api/pixies", json={"name": "Tester"})).json()["id"]

    sent = await api.http.post(f"/api/pixies/{pid}/messages", json={"text": "hello"})
    await until(lambda: bool(api.provider.runs))
    reset = await api.http.post(f"/api/pixies/{pid}/reset")
    sessions = await api.http.get("/api/sessions")

    assert sent.status_code == 202
    assert sent.json()["pixie_id"] == pid
    assert reset.json()["chat_session_id"] is None
    assert sessions.json() == []


async def test_a_message_sent_while_the_pixie_works_comes_back_queued(api: Api) -> None:
    gate = asyncio.Event()

    async def slow(run: FakeRun) -> None:
        await gate.wait()
        await reply("first")(run)

    api.provider.script(slow, reply("second"))
    pid = (await api.http.post("/api/pixies", json={"name": "Tester"})).json()["id"]

    first = await api.http.post(f"/api/pixies/{pid}/messages", json={"text": "go"})
    chat_id = first.json()["id"]
    await reach(api, chat_id, "running")
    queued = await api.http.post(f"/api/pixies/{pid}/messages", json={"text": "and this"})
    gate.set()
    await reach(api, chat_id, "idle", results=2)

    assert first.json()["queued_message"] is None
    assert queued.status_code == 202
    assert queued.json()["id"] == chat_id
    assert queued.json()["queued_message"]["text"] == "and this"


async def test_a_pixie_turn_notifies_finished_without_a_review(api: Api) -> None:
    api.provider.script(edit({"notes.md": "x"}, then=reply("done")))
    pid = (await api.http.post("/api/pixies", json={"name": "Tester"})).json()["id"]
    # A git work tree with a new file would earn any other chat a review (D072 says not here).
    git(api.ctx.paths.pixies_dir / pid / "workdir", "init", "-q")

    chat = (await api.http.post(f"/api/pixies/{pid}/messages", json={"text": "go"})).json()
    await notified(api, chat["id"], "finished")
    approvals = await api.http.get("/api/approvals")
    events = (await api.http.get(f"/api/sessions/{chat['id']}/events")).json()

    assert [a for a in approvals.json() if a["session_id"] == chat["id"]] == []
    notices = [e["payload"] for e in events if e["type"] == types.NOTIFY]
    assert "review_ready" not in [n["kind"] for n in notices]
    assert {(n["pixie_id"], n["pixie_name"]) for n in notices} == {(pid, "Tester")}


async def test_files(api: Api) -> None:
    pid = (await api.http.post("/api/pixies", json={"name": "T", "soul": "One"})).json()["id"]
    soul = (await api.http.get(f"/api/pixies/{pid}/files/soul")).json()

    saved = await api.http.put(
        f"/api/pixies/{pid}/files/soul", json={"text": "Two", "hash": soul["hash"]}
    )
    stale = await api.http.put(
        f"/api/pixies/{pid}/files/soul", json={"text": "Three", "hash": soul["hash"]}
    )
    note = await api.http.put(f"/api/pixies/{pid}/files/notes/a", json={"text": "x", "hash": None})
    traversal = await api.http.get(f"/api/pixies/{pid}/files/notes/..%2FSOUL")
    notes = await api.http.get(f"/api/pixies/{pid}/notes")
    hits = await api.http.get(f"/api/pixies/{pid}/search", params={"q": "x"})

    assert soul["text"] == "One\n"
    assert saved.json()["text"] == "Two\n"
    assert stale.status_code == 409
    assert stale.json()["code"] == "stale_file"
    assert stale.json()["text"] == "Two\n"
    assert note.status_code == 200
    assert traversal.status_code == 422
    assert notes.json() == ["a"]
    assert hits.json() == [{"file": "notes/a.md", "line": "x"}]


@pytest.mark.parametrize("pixie_id", ["nope", "0" * 32])
async def test_files_of_an_unknown_pixie_are_not_found(api: Api, pixie_id: str) -> None:
    base = f"/api/pixies/{pixie_id}"
    responses = [
        await api.http.get(f"{base}/files/soul"),
        await api.http.put(f"{base}/files/soul", json={"text": "x", "hash": None}),
        await api.http.get(f"{base}/notes"),
        await api.http.get(f"{base}/search", params={"q": "x"}),
    ]

    assert [r.status_code for r in responses] == [404, 404, 404, 404]


@pytest.mark.parametrize("query", ["", "?purge=true"])
async def test_a_pixie_chat_is_not_deleted_as_a_session(api: Api, query: str) -> None:
    api.provider.script(reply("hi"))
    pid = (await api.http.post("/api/pixies", json={"name": "Tester"})).json()["id"]
    chat = (await api.http.post(f"/api/pixies/{pid}/messages", json={"text": "go"})).json()
    await notified(api, chat["id"], "finished")

    refused = await api.http.delete(f"/api/sessions/{chat['id']}{query}")
    after = await api.http.get(f"/api/sessions/{chat['id']}")

    assert refused.status_code == 409
    assert refused.json()["code"] == "pixie_chat"
    assert after.json()["state"] == "idle"
    assert (await api.http.get(f"/api/pixies/{pid}")).json()["chat_session_id"] == chat["id"]


async def test_files_of_a_pixie_chat_cannot_be_restored(api: Api) -> None:
    api.provider.script(reply("hi"))
    pid = (await api.http.post("/api/pixies", json={"name": "Tester"})).json()["id"]
    chat = (await api.http.post(f"/api/pixies/{pid}/messages", json={"text": "go"})).json()
    await notified(api, chat["id"], "finished")
    events = (await api.http.get(f"/api/sessions/{chat['id']}/events")).json()
    message = next(e["id"] for e in events if e["type"] == types.SESSION_USER_MESSAGE)

    preview = await api.http.get(f"/api/sessions/{chat['id']}/rewind", params={"message": message})
    restore = await api.http.post(f"/api/sessions/{chat['id']}/rewind", json={"message": message})

    assert [preview.status_code, restore.status_code] == [409, 409]
    assert [preview.json()["code"], restore.json()["code"]] == ["pixie_chat", "pixie_chat"]
    assert "pixie" in restore.json()["detail"]


async def test_reorder(api: Api) -> None:
    ids = [(await api.http.post("/api/pixies", json={"name": n})).json()["id"] for n in ("A", "B")]

    ordered = await api.http.put("/api/pixies/order", json={"ids": ids[::-1]})
    missing = await api.http.put("/api/pixies/order", json={"ids": ids[:1]})
    twice = await api.http.put("/api/pixies/order", json={"ids": [*ids, ids[0]]})
    listed = await api.http.get("/api/pixies")

    assert ordered.status_code == 200
    assert [(p["id"], p["position"]) for p in ordered.json()] == [(ids[1], 0), (ids[0], 1)]
    assert [missing.status_code, twice.status_code] == [422, 422]
    assert [p["id"] for p in listed.json()] == ids[::-1]


async def test_an_explicit_null_clears_the_model_and_effort(api: Api) -> None:
    pid = (
        await api.http.post("/api/pixies", json={"name": "T", "model": "opus", "effort": "high"})
    ).json()["id"]

    kept = await api.http.patch(f"/api/pixies/{pid}", json={"mascot": "ghost"})
    cleared = await api.http.patch(f"/api/pixies/{pid}", json={"model": None, "effort": None})

    assert (kept.json()["model"], kept.json()["effort"]) == ("opus", "high")
    assert (cleared.json()["model"], cleared.json()["effort"]) == (None, None)


async def test_auto_needs_a_model_that_supports_it(api: Api) -> None:
    api.engine.info = server_info("default", "opus", "haiku", auto=("opus",))
    assert await api.ctx.engine.refresh()
    pid = (
        await api.http.post(
            "/api/pixies", json={"name": "T", "model": "opus", "permission_mode": "auto"}
        )
    ).json()["id"]

    refused = await api.http.patch(
        f"/api/pixies/{pid}", json={"model": "haiku", "permission_mode": "auto"}
    )
    moved = await api.http.patch(f"/api/pixies/{pid}", json={"model": "haiku"})

    assert refused.status_code == 422
    assert refused.json() == {"detail": "Haiku does not support Auto mode"}
    assert (moved.json()["model"], moved.json()["permission_mode"]) == ("haiku", "default")


@pytest.mark.parametrize(
    ("field", "value", "status"),
    [
        ("max_running", 1, 200),
        ("max_running", 20, 200),
        ("max_running", 0, 422),
        ("max_running", 21, 422),
        ("max_per_day", 1, 200),
        ("max_per_day", 100, 200),
        ("max_per_day", 0, 422),
        ("max_per_day", 101, 422),
    ],
)
async def test_limits_are_patched_within_their_ranges(
    api: Api, field: str, value: int, status: int
) -> None:
    pid = (await api.http.post("/api/pixies", json={"name": "Boss"})).json()["id"]

    patched = await api.http.patch(f"/api/pixies/{pid}", json={field: value})

    assert patched.status_code == status
    if status == 200:
        assert patched.json()[field] == value


async def test_a_new_pixie_has_the_default_limits_and_an_empty_activity_log(api: Api) -> None:
    created = (await api.http.post("/api/pixies", json={"name": "Boss"})).json()

    activity = await api.http.get(f"/api/pixies/{created['id']}/activity")
    unknown = await api.http.get("/api/pixies/nope/activity")

    assert (created["max_running"], created["max_per_day"]) == (2, 5)
    assert activity.status_code == 200
    assert activity.json() == []
    assert unknown.status_code == 404
