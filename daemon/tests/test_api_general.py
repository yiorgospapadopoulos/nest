"""General (B110): chats with no project, in a folder Nest owns, with no git surface."""

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from tests.api_client import Api, running_api
from tests.fake_provider import reply
from tests.fakes import FakeClock, FakeSecretStore
from tests.git_support import init_repo
from tests.test_api_sessions import reach

BUILT_IN = {"detail": "General is built in and cannot be changed or removed"}
NOT_GIT = {"detail": "general is not a git repository", "code": "not_a_git_repository"}


@pytest.fixture
async def api(tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore) -> AsyncIterator[Api]:
    async with running_api(tmp_path, clock, secrets) as running:
        yield running


def general_folder(api: Api) -> Path:
    return api.ctx.paths.data_dir / "general"


async def chat(api: Api, **fields: object) -> dict[str, Any]:
    response = await api.http.post(
        "/api/sessions", json={"repo": "general", "prompt": "How much disk is free?", **fields}
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_general_is_built_in_and_not_listed_with_the_projects(api: Api) -> None:
    repo = await api.http.get("/api/repos/general")

    assert repo.status_code == 200
    assert (repo.json()["name"], repo.json()["git"], repo.json()["path"]) == (
        "general",
        False,
        str(general_folder(api)),
    )
    assert (await api.http.get("/api/repos")).json() == []
    assert not (api.ctx.paths.repos_dir / "general.toml").exists()


async def test_a_general_chat_runs_in_place_in_the_folder_nest_creates(api: Api) -> None:
    assert not general_folder(api).exists()
    api.provider.script(reply("About 120 GB"))

    session = await chat(api, mode="worktree")
    await reach(api, session["id"], "idle", results=1)

    assert general_folder(api).is_dir()
    assert (session["repo"], session["mode"], session["cwd"]) == (
        "general",
        "in_place",
        str(general_folder(api)),
    )
    assert (session["branch"], session["worktree_path"], session["base_ref"]) == (None,) * 3
    assert api.provider.runs[0].spec.cwd == general_folder(api)
    assert api.provider.runs[0].spec.guard_git is False
    listed = (await api.http.get("/api/sessions", params={"repo": "general"})).json()
    assert [s["id"] for s in listed] == [session["id"]]
    assert (await api.http.get("/api/approvals")).json() == []


async def test_general_chats_have_no_git_surface(api: Api) -> None:
    api.provider.script(reply("Done"))
    session = await chat(api)
    await reach(api, session["id"], "idle", results=1)

    responses = [
        await api.http.get(f"/api/sessions/{session['id']}/diff"),
        await api.http.get("/api/repos/general/branches"),
        await api.http.get("/api/repos/general/branch-map"),
        await api.http.get("/api/repos/general/link-suggestions"),
    ]

    assert [(r.status_code, r.json()) for r in responses] == [(409, NOT_GIT)] * 4


async def test_general_stays_a_plain_folder_after_git_init(api: Api) -> None:
    """A `git init` in the folder never turns General into a git project."""
    api.provider.script(reply("Done"))
    await chat(api)
    init_repo(general_folder(api))

    repo = (await api.http.get("/api/repos/general")).json()

    assert (repo["git"], repo["current_branch"]) == (False, None)
    assert not (api.ctx.paths.repos_dir / "general.toml").exists()


async def test_general_cannot_be_changed_or_removed(api: Api) -> None:
    api.provider.script(reply("Done"))
    session = await chat(api)
    await reach(api, session["id"], "idle", results=1)

    responses = [
        await api.http.patch("/api/repos/general", json={"icon": "bluebell"}),
        await api.http.delete("/api/repos/general", params={"purge_sessions": True}),
    ]

    assert [(r.status_code, r.json()) for r in responses] == [(409, BUILT_IN)] * 2
    assert (await api.http.get(f"/api/sessions/{session['id']}")).status_code == 200


@pytest.mark.parametrize("name", ["general", "General", None])
async def test_the_name_general_is_refused_for_a_project(
    api: Api, tmp_path: Path, name: str | None
) -> None:
    folder = init_repo(tmp_path / "general")

    response = await api.http.post("/api/repos", json={"path": str(folder), "name": name})

    assert response.status_code == 422
    assert response.json() == {
        "detail": "the name general is kept for General's chats; choose another name"
    }
    assert (await api.http.get("/api/repos")).json() == []


async def test_reordering_ignores_general(api: Api, tmp_path: Path) -> None:
    folder = init_repo(tmp_path / "app")
    await api.http.post("/api/repos", json={"path": str(folder)})

    response = await api.http.put("/api/repos/order", json={"order": ["general", "app"]})

    assert [repo["name"] for repo in response.json()] == ["app"]
