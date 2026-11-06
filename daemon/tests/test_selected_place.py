"""The selected place of a project (B131): where new chats start until the user clicks
somewhere else. It moves nothing, and falls back to the project folder once it is gone.
"""

import json
import shutil
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from pydantic import JsonValue

from nestd.config.models import RepoConfig
from nestd.events import types
from nestd.repos.places import PlaceBook
from nestd.repos.service import PlaceReading, SelectedPlace
from nestd.storage.db import Database
from tests.api_client import Api, running_api
from tests.fake_provider import reply
from tests.fakes import FakeClock, FakeSecretStore
from tests.git_support import commit_file, git, init_repo
from tests.test_api_sessions import reach


@pytest.fixture
async def api(tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore) -> AsyncIterator[Api]:
    async with running_api(tmp_path, clock, secrets) as running:
        await running.http.post("/api/repos", json={"path": str(init_repo(tmp_path / "repo"))})
        notes = tmp_path / "notes"
        notes.mkdir()
        await running.http.post("/api/repos", json={"path": str(notes)})
        yield running


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = (tmp_path / "repo").resolve()
    git(path, "branch", "wip")
    return path


async def select(api: Api, **body: str) -> JsonValue:
    response = await api.http.put("/api/repos/repo/selected-place", json=body)
    assert response.status_code == 200, response.text
    return response.json()["selected_place"]


async def selected(api: Api) -> JsonValue:
    return (await api.http.get("/api/repos/repo")).json()["selected_place"]


async def gone(api: Api) -> JsonValue:
    return (await api.http.get("/api/repos/repo")).json()["selected_place_gone"]


def add_worktree(repo: Path, tmp_path: Path, branch: str = "agent/x") -> Path:
    path = (tmp_path / "tree").resolve()
    git(repo, "worktree", "add", "-q", "-b", branch, str(path))
    return path


async def test_a_branch_is_selected_replaced_and_cleared(api: Api, repo: Path) -> None:
    assert await selected(api) is None

    first = await select(api, branch="wip")
    second = await select(api, branch="main")
    listed = (await api.http.get("/api/repos")).json()
    assert next(item for item in listed if item["name"] == "repo")["selected_place"] == second
    cleared = await select(api)

    assert first == {"branch": "wip", "worktree_path": None}
    assert second == {"branch": "main", "worktree_path": None}
    assert cleared is None
    assert await selected(api) is None


async def test_selecting_a_worktree_stores_it_with_its_branch(
    api: Api, repo: Path, tmp_path: Path
) -> None:
    path = add_worktree(repo, tmp_path)

    assert await select(api, worktree_path=str(path)) == {
        "branch": "agent/x",
        "worktree_path": str(path),
    }


async def test_selecting_is_announced_to_other_devices(api: Api, repo: Path) -> None:
    await select(api, branch="wip")

    rows = await api.ctx.db.fetch_all(
        "SELECT payload FROM events WHERE type = ? ORDER BY id DESC", (types.REPO_UPDATED,)
    )
    assert json.loads(rows[0]["payload"])["repo"]["selected_place"] == {
        "branch": "wip",
        "worktree_path": None,
    }


async def test_the_selection_survives_a_restart(tmp_path: Path) -> None:
    path = init_repo(tmp_path / "repo")
    git(path, "branch", "wip")
    project = RepoConfig(name="repo", path=path)
    database = await Database.open(tmp_path / "nest.db")
    await PlaceBook(database).select(project, "wip", None)
    await database.close()

    database = await Database.open(tmp_path / "nest.db")
    found = await PlaceBook(database).current(project)
    await database.close()

    assert found == PlaceReading(SelectedPlace(branch="wip"))


async def test_a_deleted_branch_falls_back_to_the_folder_and_stays_forgotten(
    api: Api, repo: Path
) -> None:
    await select(api, branch="wip")

    git(repo, "branch", "-D", "wip")
    assert await selected(api) is None
    git(repo, "branch", "wip")
    assert await selected(api) is None


async def test_a_gone_place_is_reported_until_cleared(api: Api, repo: Path) -> None:
    """A client that was not watching when it went still has to tell the user."""
    await select(api, branch="wip")
    assert await gone(api) is None
    git(repo, "branch", "-D", "wip")

    first, second = await gone(api), await gone(api)
    git(repo, "branch", "wip")
    after_it_came_back = await gone(api)
    assert await selected(api) is None
    cleared = await api.http.put("/api/repos/repo/selected-place", json={})

    assert [first, second, after_it_came_back] == ["wip", "wip", "wip"]
    assert cleared.json()["selected_place_gone"] is None
    assert await gone(api) is None


async def test_clearing_a_gone_mark_takes_the_mark_and_announces_it(api: Api, repo: Path) -> None:
    await select(api, branch="wip")
    git(repo, "branch", "-D", "wip")
    assert await gone(api) == "wip"

    cleared = await api.http.delete("/api/repos/repo/selected-place/gone")

    assert cleared.status_code == 200
    assert cleared.json()["selected_place_gone"] is None
    assert cleared.json()["selected_place"] is None
    assert await gone(api) is None
    rows = await api.ctx.db.fetch_all(
        "SELECT payload FROM events WHERE type = ? ORDER BY id DESC", (types.REPO_UPDATED,)
    )
    assert json.loads(rows[0]["payload"])["repo"]["selected_place_gone"] is None


async def test_clearing_a_gone_mark_leaves_a_live_selection_alone(api: Api, repo: Path) -> None:
    """Another client may select in the moment this one clears what it saw gone."""
    place = await select(api, branch="wip")

    cleared = await api.http.delete("/api/repos/repo/selected-place/gone")

    assert cleared.status_code == 200
    assert cleared.json()["selected_place"] == place
    assert await selected(api) == place


async def test_a_new_selection_clears_a_gone_place(api: Api, repo: Path) -> None:
    await select(api, branch="wip")
    git(repo, "branch", "-D", "wip")
    assert await gone(api) == "wip"

    await select(api, branch="main")

    assert await gone(api) is None
    assert await selected(api) == {"branch": "main", "worktree_path": None}


async def test_a_removed_worktree_is_reported_by_its_branch(
    api: Api, repo: Path, tmp_path: Path
) -> None:
    path = add_worktree(repo, tmp_path)
    await select(api, worktree_path=str(path))

    git(repo, "worktree", "remove", str(path))

    assert await gone(api) == "agent/x"


async def test_a_gone_place_survives_a_restart_until_cleared(tmp_path: Path) -> None:
    path = init_repo(tmp_path / "repo")
    git(path, "branch", "wip")
    project = RepoConfig(name="repo", path=path)
    database = await Database.open(tmp_path / "nest.db")
    await PlaceBook(database).select(project, "wip", None)
    git(path, "branch", "-D", "wip")
    assert await PlaceBook(database).current(project) == PlaceReading(gone="wip")
    await database.close()

    database = await Database.open(tmp_path / "nest.db")
    book = PlaceBook(database)
    found = await book.current(project)
    await book.select(project, None, None)
    cleared = await book.current(project)
    await database.close()

    assert found == PlaceReading(gone="wip")
    assert cleared == PlaceReading()


async def test_a_branch_under_a_deleted_one_does_not_keep_it(api: Api, repo: Path) -> None:
    git(repo, "branch", "feat")
    await select(api, branch="feat")

    git(repo, "branch", "-D", "feat")
    git(repo, "branch", "feat/x")

    assert await selected(api) is None


async def test_a_removed_worktree_falls_back_even_if_its_branch_survives(
    api: Api, repo: Path, tmp_path: Path
) -> None:
    path = add_worktree(repo, tmp_path)
    await select(api, worktree_path=str(path))

    git(repo, "worktree", "remove", str(path))

    assert await selected(api) is None
    assert git(repo, "branch", "--list", "agent/x").strip() == "agent/x"


async def test_a_worktree_with_its_folder_deleted_falls_back(
    api: Api, repo: Path, tmp_path: Path
) -> None:
    path = add_worktree(repo, tmp_path)
    await select(api, worktree_path=str(path))

    shutil.rmtree(path)

    assert await selected(api) is None


async def test_a_worktree_gone_detached_falls_back(api: Api, repo: Path, tmp_path: Path) -> None:
    path = add_worktree(repo, tmp_path)
    await select(api, worktree_path=str(path))

    git(path, "checkout", "-q", "--detach")

    assert await selected(api) is None


async def test_the_selection_follows_a_worktree_to_its_new_branch(
    api: Api, repo: Path, tmp_path: Path
) -> None:
    path = add_worktree(repo, tmp_path)
    await select(api, worktree_path=str(path))

    git(path, "checkout", "-q", "-b", "agent/renamed")

    moved = {"branch": "agent/renamed", "worktree_path": str(path)}
    assert await selected(api) == moved
    assert await selected(api) == moved


async def test_a_project_git_cannot_read_keeps_its_selection(api: Api, repo: Path) -> None:
    await select(api, branch="wip")
    away = repo.with_name("away")
    shutil.move(repo, away)

    while_gone = await selected(api)
    shutil.move(away, repo)

    assert while_gone == {"branch": "wip", "worktree_path": None}
    assert await selected(api) == while_gone


@pytest.mark.parametrize(
    "body",
    [
        {"branch": "nope"},
        {"branch": "wi"},
        {"branch": "refs/heads/wip"},
        {"branch": "HEAD"},
        {"worktree_path": "/no/such/tree"},
        {"branch": "wip", "worktree_path": "/no/such/tree"},
    ],
)
async def test_unknown_places_are_refused(api: Api, repo: Path, body: dict[str, str]) -> None:
    await select(api, branch="main")

    response = await api.http.put("/api/repos/repo/selected-place", json=body)

    assert response.status_code == 422
    assert await selected(api) == {"branch": "main", "worktree_path": None}


async def test_the_project_folder_itself_is_not_a_worktree_to_select(api: Api, repo: Path) -> None:
    response = await api.http.put(
        "/api/repos/repo/selected-place", json={"worktree_path": str(repo)}
    )

    assert response.status_code == 422


async def test_a_detached_worktree_is_refused(api: Api, repo: Path, tmp_path: Path) -> None:
    path = (tmp_path / "loose").resolve()
    git(repo, "worktree", "add", "-q", "--detach", str(path))

    response = await api.http.put(
        "/api/repos/repo/selected-place", json={"worktree_path": str(path)}
    )

    assert response.status_code == 422


@pytest.mark.parametrize("breakage", ["config", "objects"])
async def test_a_broken_repo_is_a_conflict_with_gits_reason(
    api: Api, repo: Path, breakage: str
) -> None:
    if breakage == "config":
        with (repo / ".git" / "config").open("a", encoding="utf-8") as config:
            config.write("[bad\n")
    else:
        shutil.rmtree(repo / ".git" / "objects")

    response = await api.http.put("/api/repos/repo/selected-place", json={"branch": "wip"})

    assert response.status_code == 409
    assert list(response.json()) == ["detail"]
    assert response.json()["detail"].startswith("fatal: ")
    assert "\n" not in response.json()["detail"]


async def test_a_plain_folder_and_an_unknown_project_have_no_place(api: Api) -> None:
    plain = await api.http.put("/api/repos/notes/selected-place", json={})
    unknown = await api.http.put("/api/repos/nope/selected-place", json={})

    assert plain.status_code == 409
    assert unknown.status_code == 404


async def test_removing_a_project_forgets_its_selection(
    api: Api, repo: Path, tmp_path: Path
) -> None:
    await select(api, branch="wip")

    removed = await api.http.delete("/api/repos/repo")
    await api.http.post("/api/repos", json={"path": str(repo)})

    assert removed.status_code == 204
    assert await selected(api) is None


async def test_selecting_moves_no_chat_and_not_the_folder(
    api: Api, repo: Path, tmp_path: Path
) -> None:
    worktree = add_worktree(repo, tmp_path)
    commit_file(worktree, "work.txt")
    api.provider.script(reply("Done"), reply("Done"))
    in_place = await api.http.post(
        "/api/sessions", json={"repo": "repo", "prompt": "Here", "mode": "in_place"}
    )
    joined = await api.http.post(
        "/api/sessions", json={"repo": "repo", "prompt": "There", "worktree_path": str(worktree)}
    )
    chats = [str(in_place.json()["id"]), str(joined.json()["id"])]
    for chat in chats:
        await reach(api, chat, "idle", results=1)
    before = [(await api.http.get(f"/api/sessions/{chat}")).json() for chat in chats]
    head = git(repo, "rev-parse", "--symbolic-full-name", "HEAD")
    commit = git(repo, "rev-parse", "HEAD")
    tree_branch = git(worktree, "rev-parse", "--symbolic-full-name", "HEAD")

    await select(api, branch="wip")
    await select(api, worktree_path=str(worktree))
    await select(api, branch="main")
    await select(api)

    after = [(await api.http.get(f"/api/sessions/{chat}")).json() for chat in chats]
    assert after == before
    assert git(repo, "rev-parse", "--symbolic-full-name", "HEAD") == head
    assert git(repo, "rev-parse", "HEAD") == commit
    assert git(worktree, "rev-parse", "--symbolic-full-name", "HEAD") == tree_branch
