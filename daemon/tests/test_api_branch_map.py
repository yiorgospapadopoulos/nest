"""The branch map of a project (B96): its branches and worktrees, each hanging from the
branch it comes from, read from real git repositories.
"""

import shutil
from collections.abc import AsyncIterator, Mapping
from pathlib import Path

import pytest
from pydantic import JsonValue

from nestd.events import types
from nestd.repos import branch_map as branch_map_module
from tests.api_client import Api, running_api
from tests.api_support import as_old_chats
from tests.async_support import until
from tests.fake_provider import reply
from tests.fakes import FakeClock, FakeSecretStore
from tests.git_support import commit_file, git, init_repo
from tests.test_api_sessions import reach

NOT_GIT = {"detail": "notes is not a git repository", "code": "not_a_git_repository"}
MAIN_ROW = {
    "name": "main",
    "parent": None,
    "worktree": None,
    "here": True,
    "behind": 0,
    "remote": None,
}


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


def add_remote(repo: Path, path: Path, name: str = "origin") -> Path:
    """A bare copy of `repo` as its remote `name`, fetched, like a project on GitHub."""
    git(repo, "clone", "-q", "--bare", ".", str(path))
    git(repo, "remote", "add", name, str(path))
    git(repo, "fetch", "-q", name, f"+refs/heads/*:refs/remotes/{name}/*")
    return path


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
        "detached": False,
        "branches": [MAIN_ROW],
        "remote_branches": [],
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
        ("wip", "main", None, True),
        ("agent/icons", "wip", "nest", False),
        ("agent/nested", "agent/icons", "nest", False),
        ("worktree-cozy-otter", "wip", "claude", False),
        ("hotfix", "main", "other", False),
        ("stale", "main", None, False),
    ]
    branches = payload["branches"]
    assert isinstance(branches, list)
    assert branches[2] == {
        "name": "agent/icons",
        "parent": "wip",
        "worktree": {"path": str(icons), "owner": "nest"},
        "here": False,
        "behind": 0,
        "remote": None,
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
        ("wip", "main", None, True),
        ("agent/a", "wip", "nest", False),
        ("agent/b", "wip", "nest", False),
        ("agent/c", "main", "nest", False),
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

    assert rows(await branch_map(api)) == [
        ("main", None, None, True),
        ("feature", "main", None, False),
        ("fix/login", "feature", "nest", False),
    ]
    git(repo, "checkout", "-q", "feature")
    assert rows(await branch_map(api)) == [
        ("main", None, None, False),
        ("feature", "main", None, True),
        ("fix/login", "feature", "nest", False),
    ]


async def test_only_a_really_detached_folder_says_so(api: Api, repo: Path) -> None:
    async def read() -> object:
        return (await api.http.get("/api/repos/repo/branch-map")).json()["detached"]

    assert await read() is False
    git(repo, "checkout", "-q", "--orphan", "unborn")
    assert await read() is False
    git(repo, "checkout", "-q", "main")
    git(repo, "checkout", "-q", "--detach")
    assert await read() is True


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

    assert rows(await branch_map(api)) == [
        ("main", None, None, True),
        ("gone", "main", None, False),
    ]


async def test_a_branch_shows_once_and_one_without_commits_not_at_all(
    api: Api, repo: Path, tmp_path: Path
) -> None:
    # main again, forced, in a second folder: it stays the project folder's.
    git(repo, "worktree", "add", "-q", "--force", str(tmp_path / "again"), "main")
    git(repo, "worktree", "add", "-q", "--orphan", "-b", "empty", str(tmp_path / "orphan"))

    assert await branch_map(api) == {
        "default_branch": "main",
        "current_branch": "main",
        "detached": False,
        "branches": [MAIN_ROW],
        "remote_branches": [],
    }


async def test_a_repo_without_commits_has_no_branches(api: Api, tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    git(empty, "init", "-q", "-b", "main")
    await api.http.post("/api/repos", json={"path": str(empty)})

    assert await branch_map(api, "empty") == {
        "default_branch": "main",
        "current_branch": None,
        "detached": False,
        "branches": [],
        "remote_branches": [],
    }


async def test_every_local_branch_shows_each_under_the_one_it_comes_from(
    api: Api, repo: Path
) -> None:
    git(repo, "checkout", "-q", "-b", "feat/a")
    commit_file(repo, "a.txt")
    git(repo, "checkout", "-q", "-b", "feat/b")
    commit_file(repo, "b.txt")
    git(repo, "checkout", "-q", "main")

    assert rows(await branch_map(api)) == [
        ("main", None, None, True),
        ("feat/a", "main", None, False),
        ("feat/b", "feat/a", None, False),
    ]


async def test_a_worktree_on_the_default_branch_keeps_its_mark(api: Api, repo: Path) -> None:
    # The folder moves away, so main can be checked out in a linked worktree.
    git(repo, "checkout", "-q", "-b", "wip")
    git(repo, "worktree", "add", "-q", str(worktrees(repo) / "nest-12345678"), "main")

    assert rows(await branch_map(api)) == [
        ("main", None, "nest", False),
        ("wip", "main", None, True),
    ]


async def test_past_the_cap_all_branches_show_and_worktrees_stay_bases(
    api: Api, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(branch_map_module, "MAX_BASES", 2)
    old = add_worktree(repo, worktrees(repo) / "nest-12345678", "old", "main")
    commit_file(old, "old.txt")
    git(old, "checkout", "-q", "-b", "child")
    commit_file(old, "child.txt")
    git(old, "checkout", "-q", "old")
    git(repo, "checkout", "-q", "-b", "newer")
    commit_file(repo, "newer.txt")
    git(repo, "checkout", "-q", "main")
    git(repo, "branch", "newest", "newer")

    assert rows(await branch_map(api)) == [
        ("main", None, None, True),
        ("old", "main", "nest", False),
        ("child", "old", None, False),
        # `newer` is past the cap, so its twin cannot hang from it.
        ("newer", "main", None, False),
        ("newest", "main", None, False),
    ]


async def test_a_local_main_tops_the_map_whatever_the_folder_and_default_are_on(
    api: Api, repo: Path
) -> None:
    git(repo, "checkout", "-q", "-b", "wip")
    commit_file(repo, "wip.txt")
    add_worktree(repo, worktrees(repo) / "nest-12345678", "agent/x", "wip")
    edited = await api.http.patch("/api/repos/repo", json={"default_branch": "wip"})
    assert edited.status_code == 200

    payload = await branch_map(api)

    assert payload["default_branch"] == "wip"
    assert payload["current_branch"] == "wip"
    assert rows(payload) == [
        ("main", None, None, False),
        ("wip", "main", None, True),
        ("agent/x", "wip", "nest", False),
    ]


async def test_main_only_on_remotes_tops_the_map_from_origin_and_leaves_its_list(
    api: Api, repo: Path, tmp_path: Path
) -> None:
    add_remote(repo, tmp_path / "backup.git", "backup")
    add_remote(repo, tmp_path / "origin.git")
    git(repo, "checkout", "-q", "-b", "wip")
    commit_file(repo, "wip.txt")
    git(repo, "branch", "-D", "main")

    payload = await branch_map(api)

    assert rows(payload) == [("main", None, None, False), ("wip", "main", None, True)]
    branches = payload["branches"]
    assert isinstance(branches, list)
    assert branches[0] == {
        "name": "main",
        "parent": None,
        "worktree": None,
        "here": False,
        "behind": 0,
        "remote": "origin",
    }
    assert payload["remote_branches"] == [{"remote": "backup", "name": "main"}]


async def test_a_remotes_head_tops_the_map_when_there_is_no_main(
    api: Api, repo: Path, tmp_path: Path
) -> None:
    git(repo, "branch", "-m", "main", "trunk")
    git(repo, "branch", "develop")
    add_remote(repo, tmp_path / "origin.git")
    git(repo, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/develop")

    local = await branch_map(api)
    git(repo, "branch", "-D", "develop")
    remote_only = await branch_map(api)

    assert rows(local) == [("develop", None, None, False), ("trunk", "develop", None, True)]
    assert rows(remote_only) == [("develop", None, None, False), ("trunk", "develop", None, True)]
    branches = remote_only["branches"]
    assert isinstance(branches, list)
    top = branches[0]
    assert isinstance(top, dict)
    assert top["remote"] == "origin"


async def test_a_head_at_a_gone_branch_counts_as_unknown(
    api: Api, repo: Path, tmp_path: Path
) -> None:
    git(repo, "branch", "-m", "main", "trunk")
    git(repo, "branch", "master")
    add_remote(repo, tmp_path / "origin.git")
    git(repo, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/gone")

    assert rows(await branch_map(api))[0] == ("master", None, None, False)


async def test_a_local_master_goes_ahead_of_the_default_setting(api: Api, repo: Path) -> None:
    git(repo, "branch", "-m", "main", "trunk")
    git(repo, "branch", "master")
    git(repo, "checkout", "-q", "-b", "wip")
    await api.http.patch("/api/repos/repo", json={"default_branch": "trunk"})

    top = rows(await branch_map(api))[0]
    git(repo, "branch", "-D", "master")

    assert top == ("master", None, None, False)
    assert rows(await branch_map(api))[0] == ("trunk", None, None, False)


async def test_a_chats_base_stays_measured_from_the_default_branch(api: Api, repo: Path) -> None:
    git(repo, "checkout", "-q", "-b", "wip")
    commit_file(repo, "wip.txt")
    fork_point = git(repo, "rev-parse", "HEAD").strip()
    git(repo, "checkout", "-q", "-b", "feature")
    commit_file(repo, "one.txt")
    # Nearer to `feature` than `wip` is, and to the map its parent.
    git(repo, "branch", "backup")
    commit_file(repo, "two.txt")
    git(repo, "checkout", "-q", "wip")
    await api.http.patch("/api/repos/repo", json={"default_branch": "wip"})
    assert ("feature", "backup", None, False) in rows(await branch_map(api))
    api.provider.script(reply("Done"))

    chat = await api.http.post(
        "/api/sessions", json={"repo": "repo", "prompt": "Do it", "on_branch": "feature"}
    )

    assert chat.json()["base_ref"] == fork_point
    await reach(api, str(chat.json()["id"]), "idle", results=1)


async def test_remote_only_branches_are_listed_once_per_remote(
    api: Api, repo: Path, tmp_path: Path
) -> None:
    git(repo, "branch", "feat/x")
    git(repo, "branch", "local")
    add_remote(repo, tmp_path / "origin.git")
    add_remote(repo, tmp_path / "other.git", "other")
    git(repo, "branch", "-D", "feat/x")
    # Gone from the config, and origin's own pointer: neither is a branch to pick.
    git(repo, "update-ref", "refs/remotes/former/old", "main")
    git(repo, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
    # `git remote add` refuses these two together, but a config can hold them, and a name
    # can start with another's.
    git(repo, "config", "remote.team.url", "/nowhere")
    git(repo, "config", "remote.team/one.url", "/nowhere")
    git(repo, "update-ref", "refs/remotes/team/fix", "main")
    git(repo, "update-ref", "refs/remotes/team/one/fix", "main")

    assert (await branch_map(api))["remote_branches"] == [
        {"remote": "origin", "name": "feat/x"},
        {"remote": "other", "name": "feat/x"},
        {"remote": "team", "name": "fix"},
        {"remote": "team/one", "name": "fix"},
    ]


async def test_changing_the_default_branch_refreshes_the_map(
    api: Api, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A client that reads the map on `repo.branches_changed` was left with the old one."""
    git(repo, "branch", "wip")
    await api.ctx.branch_watch.stop()
    announced: list[Mapping[str, JsonValue]] = []
    publish = api.ctx.bus.publish_ephemeral

    async def record(
        event_type: str, payload: Mapping[str, JsonValue], session_id: str | None = None
    ) -> object:
        if event_type == types.REPO_BRANCHES_CHANGED:
            announced.append(payload)
        return await publish(event_type, payload, session_id)

    monkeypatch.setattr(api.ctx.bus, "publish_ephemeral", record)

    await api.http.patch("/api/repos/repo", json={"icon_color": "#112233"})
    quiet = list(announced)
    await api.http.patch("/api/repos/repo", json={"default_branch": "wip"})

    assert quiet == []
    assert announced == [{"name": "repo"}]
    assert (await branch_map(api))["default_branch"] == "wip"


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
    await as_old_chats(api.ctx, *ids)
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
