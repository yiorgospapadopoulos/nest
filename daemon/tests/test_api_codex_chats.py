"""B113: Codex chats from outside Nest through the outside-chat routes, search and the
chat archiver.
"""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from nestd.config.models import StorageSettings
from nestd.events import types
from tests.api_client import Api, running_api
from tests.codex_support import CodexThreads
from tests.fakes import FakeClock, FakeSecretStore
from tests.git_support import init_repo

THREAD = "019a0000-0000-7000-8000-00000000000a"


@pytest.fixture
async def api(tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore) -> AsyncIterator[Api]:
    home = tmp_path / "codex"
    (home / "sessions").mkdir(parents=True)
    async with running_api(tmp_path, clock, secrets, codex_home=home) as running:
        await running.http.post("/api/repos", json={"path": str(init_repo(tmp_path / "repo"))})
        yield running


@pytest.fixture
def threads(api: Api, tmp_path: Path) -> CodexThreads:
    store = CodexThreads(api.codex)
    store.add(THREAD, (tmp_path / "repo").resolve(), name="Tidy the parser", model="gpt-5.5")
    return store


async def test_list_read_and_continue_a_codex_chat(api: Api, threads: CodexThreads) -> None:
    (listed,) = (await api.http.get("/api/claude-chats", params={"repo": "repo"})).json()
    assert (listed["id"], listed["engine"], listed["title"]) == (THREAD, "codex", "Tidy the parser")
    assert (await api.http.get(f"/api/claude-chats/{THREAD}")).json() == listed

    history = (await api.http.get(f"/api/claude-chats/{THREAD}/events")).json()
    assert [e["type"] for e in history] == [types.SESSION_USER_MESSAGE, types.SESSION_MESSAGE]

    adopted = await api.http.post(f"/api/claude-chats/{THREAD}/adopt")

    assert adopted.status_code == 201, adopted.text
    session = adopted.json()
    assert (session["provider"], session["provider_session_id"], session["model"]) == (
        "codex",
        THREAD,
        "gpt-5.5",
    )
    assert (session["state"], session["mode"]) == ("idle", "in_place")
    events = (await api.http.get(f"/api/sessions/{session['id']}/events")).json()
    copied = [(e["type"], e["payload"]) for e in events[2:]]
    assert copied == [(e["type"], e["payload"]) for e in history]
    # It is Nest's now: it leaves the list, and adopting again finds the session.
    assert (await api.http.get("/api/claude-chats")).json() == []
    again = await api.http.post(f"/api/claude-chats/{THREAD}/adopt")
    assert (again.status_code, again.json()["id"]) == (200, session["id"])


async def test_archive_a_codex_chat_in_codex(api: Api, threads: CodexThreads) -> None:
    archived = await api.http.put(f"/api/claude-chats/{THREAD}/archived", json={"archived": True})

    assert archived.status_code == 200
    assert archived.json()["archived"] is True
    assert api.codex.requests("thread/archive") == [{"threadId": THREAD}]
    assert [t["id"] for t in threads.archived] == [THREAD]


async def test_codex_chat_titles_are_searchable(api: Api, threads: CodexThreads) -> None:
    await api.ctx.claude_chats.refresh()

    response = await api.http.get("/api/search", params={"q": "parser"})

    (hit,) = response.json()["hits"]
    assert hit == {
        "session_id": THREAD,
        "repo": "repo",
        "title": "Tidy the parser",
        "event_id": None,
        "ts": "2026-09-21T15:13:20Z",
        "kind": "codex_chat",
        "snippet": "Tidy the [[parser]]",
    }


async def test_an_idle_codex_chat_is_archived_in_codex(api: Api, tmp_path: Path) -> None:
    store = CodexThreads(api.codex)
    root = (tmp_path / "repo").resolve()
    store.add("old", root, updatedAt=1760000000)  # 2025-10-09, before the cutoff
    store.add("recent", root, updatedAt=1767225600)  # 2026-01-01
    api.ctx.settings = api.ctx.settings.model_copy(
        update={"storage": StorageSettings(archive_after_days=7)}
    )

    assert await api.ctx.archiver.run_once() == ["old"]

    assert api.codex.requests("thread/archive") == [{"threadId": "old"}]
    assert [t["id"] for t in store.archived] == ["old"]
    assert await api.ctx.archiver.run_once() == []
