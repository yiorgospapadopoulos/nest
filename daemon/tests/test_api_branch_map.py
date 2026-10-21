"""The branch map of a project (B96): its branches and worktrees, each hanging from the
branch it comes from, read from real git repositories.
"""

import shutil
from collections.abc import AsyncIterator, Mapping
from pathlib import Path

import pytest
from pydantic import JsonValue

from nestd.events import types
from tests.api_client import Api, running_api
from tests.async_support import until
from tests.fake_provider import reply
from tests.fakes import FakeClock, FakeSecretStore
from tests.git_support import commit_file, git, init_repo
from tests.test_api_sessions import reach

NOT_GIT = {"detail": "notes is not a git repository", "code": "not_a_git_repository"}


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
    return (tmp_path / "repo").resolve()


def worktrees(repo: Path) -> Path:
    return repo / ".claude" / "worktrees"


def add_worktree(repo: Path, path: Path, branch: str, start: str) -> Path:
    git(repo, "worktree", "add", "-q", "-b", branch, str(path), start)
    return path


async def branch_map(api: Api, name: str = "repo") -> dict[str, JsonValue]:
    response = await api.http.get(f"/api/repos/{name}/branch-map")
    assert response.status_code == 200, response.text
    return response.json()


def rows(payload: Mapping[str, JsonValue]) -> list[tuple[object, ...]]:
    """(name, parent, owner, here) of each branch, in the order given."""
    result: list[tuple[object, ...]] = []
    branches = payload["branches"]
    assert isinstance(branches, list)
    for branch in branches:
        assert isinstance(branch, dict)
        worktree = branch["worktree"]
        owner = worktree["owner"] if isinstance(worktree, dict) else None
        result.append((branch["name"], branch["parent"], owner, branch["here"]))
    return result


async def test_a_repo_with_only_its_default_branch(api: Api) -> None:
    assert await branch_map(api) == {
        "default_branch": "main",
        "current_branch": "main",
        "branches": [{"name": "main", "parent": None, "worktree": None, "here": True}],
    }


async def test_worktrees_hang_from_the_branch_they_come_from(
    api: Api, repo: Path, tmp_path: Path
) -> None:
    git(repo, "branch", "stale")
    git(repo, "checkout", "-q", "-b", "wip")
    commit_file(repo, "wip1.txt")
    commit_file(repo, "wip2.txt")
    icons = add_worktree(repo, worktrees(repo) / "nest-1a2b3c4d", "agent/icons", "wip")
    commit_file(icons, "icons.txt")
    # Started from the icons worktree's branch: nested two deep.
    nested = add_worktree(repo, worktrees(repo) / "harness-0f0f0f0f", "agent/nested", "agent/icons")
    commit_file(nested, "nested.txt")
    # Claude Code's own worktree, from wip, nothing committed yet.
    add_worktree(repo, worktrees(repo) / "cozy-otter", "worktree-cozy-otter", "wip")
    # A worktree somewhere else, from main.
    hotfix = add_worktree(repo, (tmp_path / "hotfix").resolve(), "hotfix", "main")
    commit_file(hotfix, "fix.txt")
    git(repo, "worktree", "add", "-q", "--detach", str(tmp_path / "detached"), "main")

    payload = await branch_map(api)

    assert payload["default_branch"] == "main"
    assert payload["current_branch"] == "wip"
    assert rows(payload) == [
        ("main", None, None, False),
        ("hotfix", "main", "other", False),
        ("wip", "main", None, True),
        ("agent/icons", "wip", "nest", False),
        ("agent/nested", "agent/icons", "nest", False),
        ("worktree-cozy-otter", "wip", "claude", False),
    ]
    branches = payload["branches"]
    assert isinstance(branches, list)
    assert branches[3] == {
        "name": "agent/icons",
        "parent": "wip",
        "worktree": {"path": str(icons), "owner": "nest"},
        "here": False,
    }


async def test_fresh_worktrees_from_a_branch_hang_from_it_not_from_each_other(
    api: Api, repo: Path
) -> None:
    git(repo, "checkout", "-q", "-b", "wip")
    commit_file(repo, "wip.txt")
    add_worktree(repo, worktrees(repo) / "nest-aaaaaaaa", "agent/a", "wip")
    add_worktree(repo, worktrees(repo) / "nest-bbbbbbbb", "agent/b", "wip")
    # From main with nothing new: as near to main as to anything, so main.
    add_worktree(repo, worktrees(repo) / "nest-cccccccc", "agent/c", "main")

    assert rows(await branch_map(api)) == [
        ("main", None, None, False),
        ("agent/c", "main", "nest", False),
        ("wip", "main", None, True),
        ("agent/a", "wip", "nest", False),
        ("agent/b", "wip", "nest", False),
    ]


async def test_a_nest_worktree_chat_hangs_from_the_branch_it_started_from(
    api: Api, repo: Path
) -> None:
    git(repo, "checkout", "-q", "-b", "feature")
    commit_file(repo, "feature.txt")
    git(repo, "checkout", "-q", "main")
    api.provider.script(reply("Done"))
    response = await api.http.post(
        "/api/sessions",
        json={
            "repo": "repo",
            "prompt": "Do it",
            "mode": "worktree",
            "branch": "fix/login",
            "base": "feature",
        },
    )
    session = response.json()
    await reach(api, str(session["id"]), "idle", results=1)

    # `feature` is not checked out anywhere: the chat hangs from main.
    assert rows(await branch_map(api)) == [
        ("main", None, None, True),
        ("fix/login", "main", "nest", False),
    ]
    # Once `feature` is checked out in the project folder, it is shown, and the parent.
    git(repo, "checkout", "-q", "feature")
    assert rows(await branch_map(api)) == [
        ("main", None, None, False),
        ("feature", "main", None, True),
        ("fix/login", "feature", "nest", False),
    ]


async def test_a_detached_project_folder_has_no_current_branch(api: Api, repo: Path) -> None:
    add_worktree(repo, worktrees(repo) / "nest-12345678", "agent/x", "main")
    git(repo, "checkout", "-q", "--detach")

    payload = await branch_map(api)

    assert payload["current_branch"] is None
    assert rows(payload) == [("main", None, None, False), ("agent/x", "main", "nest", False)]


async def test_without_the_default_branch_the_root_is_the_current_branch(
    api: Api, repo: Path
) -> None:
    git(repo, "checkout", "-q", "-b", "trunk")
    git(repo, "branch", "-D", "main")
    add_worktree(repo, worktrees(repo) / "nest-12345678", "agent/x", "trunk")

    payload = await branch_map(api)

    assert payload["default_branch"] == "main"
    assert rows(payload) == [("trunk", None, None, True), ("agent/x", "trunk", "nest", False)]


async def test_without_the_default_or_a_current_branch_the_root_is_the_first_by_name(
    api: Api, repo: Path
) -> None:
    add_worktree(repo, worktrees(repo) / "nest-1", "zeta", "main")
    add_worktree(repo, worktrees(repo) / "nest-2", "alpha", "main")
    git(repo, "checkout", "-q", "--detach")
    git(repo, "branch", "-D", "main")

    assert rows(await branch_map(api)) == [
        ("alpha", None, "nest", False),
        ("zeta", "alpha", "nest", False),
    ]


async def test_a_worktree_whose_folder_was_deleted_is_left_out(
    api: Api, repo: Path, tmp_path: Path
) -> None:
    gone = add_worktree(repo, (tmp_path / "gone").resolve(), "gone", "main")
    shutil.rmtree(gone)

    assert rows(await branch_map(api)) == [("main", None, None, True)]


async def test_a_branch_shows_once_and_one_without_commits_not_at_all(
    api: Api, repo: Path, tmp_path: Path
) -> None:
    # main again, forced, in a second folder: it stays the project folder's.
    git(repo, "worktree", "add", "-q", "--force", str(tmp_path / "again"), "main")
    git(repo, "worktree", "add", "-q", "--orphan", "-b", "empty", str(tmp_path / "orphan"))

    assert await branch_map(api) == {
        "default_branch": "main",
        "current_branch": "main",
        "branches": [{"name": "main", "parent": None, "worktree": None, "here": True}],
    }


async def test_a_repo_without_commits_has_no_branches(api: Api, tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    git(empty, "init", "-q", "-b", "main")
    await api.http.post("/api/repos", json={"path": str(empty)})

    assert await branch_map(api, "empty") == {
        "default_branch": "main",
        "current_branch": None,
        "branches": [],
    }


async def test_branch_map_errors(api: Api, tmp_path: Path) -> None:
    unknown = await api.http.get("/api/repos/nope/branch-map")
    plain = await api.http.get("/api/repos/notes/branch-map")
    shutil.rmtree(tmp_path / "repo")
    missing = await api.http.get("/api/repos/repo/branch-map")

    assert (unknown.status_code, unknown.json()) == (404, {"detail": "unknown repo 'nope'"})
    assert (plain.status_code, plain.json()) == (409, NOT_GIT)
    assert missing.status_code == 409
    assert "no longer exists" in missing.json()["detail"]


async def test_nest_announces_the_worktrees_it_creates_and_removes(
    api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Only Nest's own announcements: the poller would see the same changes.
    await api.ctx.branch_watch.stop()
    announced: list[tuple[str, Mapping[str, JsonValue]]] = []
    publish = api.ctx.bus.publish_ephemeral

    async def record(
        event_type: str, payload: Mapping[str, JsonValue], session_id: str | None = None
    ) -> object:
        if event_type == types.REPO_BRANCHES_CHANGED:
            announced.append((event_type, payload))
        return await publish(event_type, payload, session_id)

    monkeypatch.setattr(api.ctx.bus, "publish_ephemeral", record)
    expected = (types.REPO_BRANCHES_CHANGED, {"name": "repo"})
    api.provider.script(reply("Done"), reply("Done"), reply("Done"))
    ids: list[str] = []
    for _ in range(3):
        created = await api.http.post(
            "/api/sessions", json={"repo": "repo", "prompt": "Do it", "mode": "worktree"}
        )
        ids.append(str(created.json()["id"]))
        await reach(api, ids[-1], "idle", results=1)
    assert announced.count(expected) >= 3
    removals: list[tuple[str, dict[str, bool]]] = [
        (f"/api/sessions/{ids[0]}", {"remove_worktree": True}),
        (f"/api/sessions/{ids[1]}", {"purge": True}),
    ]

    for path, params in removals:
        announced.clear()
        await api.http.delete(path, params=params)
        await until(lambda: expected in announced)
    announced.clear()
    await api.ctx.sessions.close_keeping_work(ids[2])

    assert expected in announced
