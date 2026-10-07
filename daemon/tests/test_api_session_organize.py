import asyncio
import shutil
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from tests.api_client import Api, running_api
from tests.fake_provider import reply
from tests.fakes import FakeClock, FakeSecretStore
from tests.git_support import init_repo
from tests.test_api_sessions import create, reach


@pytest.fixture
async def api(tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore) -> AsyncIterator[Api]:
    async with running_api(tmp_path, clock, secrets) as running:
        await running.http.post("/api/repos", json={"path": str(init_repo(tmp_path / "repo"))})
        yield running


async def idle_session(api: Api, prompt: str = "Do it") -> str:
    api.provider.script(reply("ok"))
    session_id = str((await create(api, prompt=prompt))["id"])
    await reach(api, session_id, "idle")
    return session_id


async def test_rename_pin_and_archive(api: Api) -> None:
    first = await idle_session(api, "please fix the flaky test. It fails on CI")
    second = await idle_session(api)

    renamed = await api.http.patch(f"/api/sessions/{second}", json={"title": "  Renamed  "})
    pinned = await api.http.patch(f"/api/sessions/{second}", json={"pinned": True})
    archived = await api.http.patch(f"/api/sessions/{first}", json={"archived": True})
    listed = await api.http.get("/api/sessions")
    hidden = await api.http.get("/api/sessions", params={"archived": "true", "repo": "repo"})
    other_repo = await api.http.get("/api/sessions", params={"repo": "other"})

    assert renamed.json()["title"] == "Renamed"
    assert pinned.json()["pinned"] is True
    assert archived.json()["archived_at"] is not None
    assert [s["id"] for s in listed.json()] == [second]
    assert [(s["id"], s["title"]) for s in hidden.json()] == [(first, "Fix the flaky test")]
    assert other_repo.json() == []


@pytest.mark.parametrize("title", ["", "   ", "x" * 121])
async def test_titles_must_have_1_to_120_characters(api: Api, title: str) -> None:
    session_id = await idle_session(api)

    response = await api.http.patch(f"/api/sessions/{session_id}", json={"title": title})

    assert response.status_code == 422


async def test_effort_changes_on_an_existing_chat(api: Api) -> None:
    session_id = await idle_session(api)

    patched = await api.http.patch(f"/api/sessions/{session_id}", json={"effort": "max"})
    invalid = await api.http.patch(f"/api/sessions/{session_id}", json={"effort": "extreme"})

    assert patched.status_code == 200
    assert patched.json()["effort"] == "max"
    assert invalid.status_code == 422
    detail = (await api.http.get(f"/api/sessions/{session_id}")).json()
    assert detail["effort"] == "max"


async def test_delete_with_purge_removes_the_session(api: Api) -> None:
    session_id = await idle_session(api)

    deleted = await api.http.delete(f"/api/sessions/{session_id}", params={"purge": True})
    gone = await api.http.get(f"/api/sessions/{session_id}")
    again = await api.http.delete(f"/api/sessions/{session_id}", params={"purge": True})

    assert deleted.status_code == 204
    assert gone.status_code == 404
    assert again.status_code == 404


async def test_purge_works_after_the_repo_folder_was_deleted(api: Api, tmp_path: Path) -> None:
    session_id = await idle_session(api)
    worktree = (await api.http.get(f"/api/sessions/{session_id}")).json()["worktree_path"]
    shutil.rmtree(tmp_path / "repo")

    deleted = await api.http.delete(f"/api/sessions/{session_id}", params={"purge": True})
    gone = await api.http.get(f"/api/sessions/{session_id}")

    assert deleted.status_code == 204, deleted.text
    assert gone.status_code == 404
    assert not await asyncio.to_thread(Path(worktree).exists)
