from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from harness.events import types
from tests.api_client import Api, running_api
from tests.async_support import until
from tests.fake_provider import edit, reply
from tests.fakes import FakeClock, FakeSecretStore
from tests.git_support import git
from tests.test_api_sessions import notified


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


async def test_a_pixie_turn_notifies_finished_without_a_review(api: Api) -> None:
    api.provider.script(edit({"notes.md": "x"}, then=reply("done")))
    pid = (await api.http.post("/api/pixies", json={"name": "Tester"})).json()["id"]
    # A git work tree with a new file would earn any other chat a review (D057 says not here).
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
