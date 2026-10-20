"""A new chat in an existing worktree of its project (B96): joining it, what is refused,
the base its work is compared with, and when a shared worktree is removed.
"""

import shutil
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from nestd.events import types
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


def repo_of(tmp_path: Path) -> Path:
    return (tmp_path / "repo").resolve()


def local_branches(repo: Path) -> list[str]:
    return git(repo, "branch", "--format=%(refname:short)").split()


def add_worktree(repo: Path, path: Path, branch: str, start: str = "main") -> Path:
    git(repo, "worktree", "add", "-q", "-b", branch, str(path), start)
    return path


async def stored(api: Api, session_id: object) -> dict[str, object]:
    return (await api.http.get(f"/api/sessions/{session_id}")).json()


async def started(api: Api, **fields: object) -> dict[str, object]:
    """A chat that has reached idle after its first turn."""
    api.provider.script(reply("Done"))
    response = await api.http.post(
        "/api/sessions", json={"repo": "repo", "prompt": "Do it", **fields}
    )
    assert response.status_code == 201, response.text
    session_id = str(response.json()["id"])
    await reach(api, session_id, "idle", results=1)
    return await stored(api, session_id)


async def nest_worktree(api: Api) -> dict[str, object]:
    return await started(api, mode="worktree", branch="feat")


async def workspace_events(api: Api, session_id: object) -> list[dict[str, object]]:
    events = (await api.http.get(f"/api/sessions/{session_id}/events")).json()
    return [e["payload"] for e in events if e["type"] == types.SESSION_WORKSPACE]


# Joining


async def test_a_chat_joins_a_nest_worktree_and_shares_its_base(api: Api, tmp_path: Path) -> None:
    repo = repo_of(tmp_path)
    (repo / ".env").write_text("SECRET=1\n", encoding="utf-8")
    await api.http.patch("/api/repos/repo", json={"link": [".env"], "setup": ["touch setup-ran"]})
    first = await nest_worktree(api)
    path = Path(str(first["worktree_path"]))
    (path / ".env").unlink()
    (path / "setup-ran").unlink()

    joined = await started(api, worktree_path=str(path))

    assert joined["mode"] == "worktree"
    assert joined["cwd"] == str(path)
    assert joined["worktree_path"] == str(path)
    assert joined["branch"] == "feat"
    assert joined["base_ref"] == first["base_ref"]
    assert sorted(p.name for p in (repo / ".claude" / "worktrees").iterdir()) == [path.name]
    assert not (path / ".env").exists()
    assert not (path / "setup-ran").exists()
    assert await workspace_events(api, joined["id"]) == [
        {
            "path": str(path),
            "branch": "feat",
            "base_ref": first["base_ref"],
            "linked": [],
            "missing": [],
            "existing": [],
            "failed": [],
        }
    ]
    assert local_branches(repo) == ["feat", "main"]


async def test_a_joined_chat_works_in_the_worktree(api: Api, tmp_path: Path) -> None:
    repo = repo_of(tmp_path)
    path = add_worktree(repo, repo / ".claude" / "worktrees" / "cc-1", "cc-x")

    await started(api, worktree_path=str(path), mode="worktree")

    assert Path(api.provider.runs[-1].spec.cwd) == path


async def test_a_claude_code_worktree_is_based_on_its_parent_in_the_branch_map(
    api: Api, tmp_path: Path
) -> None:
    repo = repo_of(tmp_path)
    git(repo, "checkout", "-q", "-b", "wip")
    fork_point = commit_file(repo, "wip.txt")
    path = add_worktree(repo, repo / ".claude" / "worktrees" / "brave-otter", "cc-x", "wip")
    commit_file(path, "cc.txt")
    commit_file(repo, "later.txt")

    joined = await started(api, worktree_path=str(path))

    assert joined["branch"] == "cc-x"
    assert joined["base_ref"] == fork_point


async def test_another_worktree_is_based_on_the_default_branch(api: Api, tmp_path: Path) -> None:
    repo = repo_of(tmp_path)
    fork_point = git(repo, "rev-parse", "main").strip()
    path = add_worktree(repo, tmp_path / "elsewhere", "side")
    commit_file(path, "side.txt")
    commit_file(repo, "later.txt")

    joined = await started(api, worktree_path=str(path))

    assert joined["branch"] == "side"
    assert joined["base_ref"] == fork_point
    assert joined["worktree_path"] == str(path.resolve())


async def test_without_a_default_branch_the_base_is_the_worktree_head(
    api: Api, tmp_path: Path
) -> None:
    repo = repo_of(tmp_path)
    path = add_worktree(repo, tmp_path / "elsewhere", "aaa")
    head = commit_file(path, "a.txt")
    git(repo, "checkout", "-q", "--detach")
    git(repo, "branch", "-D", "main")

    joined = await started(api, worktree_path=str(path))

    assert joined["base_ref"] == head


async def test_the_base_of_a_closed_chat_on_the_worktree_is_kept(api: Api) -> None:
    first = await nest_worktree(api)
    await api.http.delete(f"/api/sessions/{first['id']}")
    path = Path(str(first["worktree_path"]))
    commit_file(path, "more.txt")

    joined = await started(api, worktree_path=str(path))

    assert joined["base_ref"] == first["base_ref"]


# Refused


async def refused(api: Api, repo: str = "repo", **fields: object) -> dict[str, object]:
    response = await api.http.post("/api/sessions", json={"repo": repo, "prompt": "x", **fields})
    assert response.status_code == 422, response.text
    assert (await api.http.get("/api/sessions")).json() == []
    return response.json()


async def test_a_plain_folder_has_no_worktrees_to_join(api: Api, tmp_path: Path) -> None:
    detail = await refused(api, "notes", worktree_path=str(tmp_path / "notes"))

    assert detail == {"detail": "notes is not a git repository, so it has no worktrees to join"}


async def test_a_path_that_is_not_a_linked_worktree_is_refused(api: Api, tmp_path: Path) -> None:
    repo = repo_of(tmp_path)
    other = init_repo(tmp_path / "other")
    foreign = add_worktree(other, tmp_path / "foreign", "x")
    stray = tmp_path / "stray"
    stray.mkdir()

    details = [await refused(api, worktree_path=str(path)) for path in (repo, stray, foreign)]

    assert details == [
        {"detail": f"{path} is not a linked worktree of repo"} for path in (repo, stray, foreign)
    ]


async def test_a_relative_path_is_refused(api: Api) -> None:
    detail = await refused(api, worktree_path=".claude/worktrees/x")

    assert detail == {"detail": "worktree_path must be an absolute path"}


async def test_a_worktree_whose_folder_is_gone_is_refused(api: Api, tmp_path: Path) -> None:
    repo = repo_of(tmp_path)
    path = add_worktree(repo, tmp_path / "gone", "gone")
    shutil.rmtree(path)

    detail = await refused(api, worktree_path=str(path))

    assert detail == {"detail": f"the folder {path} does not exist"}


async def test_a_detached_worktree_is_refused(api: Api, tmp_path: Path) -> None:
    repo = repo_of(tmp_path)
    path = tmp_path / "detached"
    git(repo, "worktree", "add", "-q", "--detach", str(path), "main")

    detail = await refused(api, worktree_path=str(path))

    assert detail == {"detail": f"the worktree {path} is not on a branch"}


@pytest.mark.parametrize(
    "fields",
    [{"branch": "x"}, {"base": "main"}, {"mode": "in_place"}],
)
async def test_joining_takes_no_branch_base_or_in_place_mode(
    api: Api, tmp_path: Path, fields: dict[str, str]
) -> None:
    path = add_worktree(repo_of(tmp_path), tmp_path / "w", "w")

    detail = await refused(api, worktree_path=str(path), **fields)

    assert detail == {"detail": "a chat joining a worktree takes no branch, base or in-place mode"}


# Removing a shared worktree


async def pair(api: Api) -> tuple[dict[str, object], dict[str, object], Path]:
    first = await nest_worktree(api)
    path = Path(str(first["worktree_path"]))
    second = await started(api, worktree_path=str(path))
    return first, second, path


async def test_closing_removes_a_shared_worktree_only_with_its_last_chat(
    api: Api, tmp_path: Path
) -> None:
    first, second, path = await pair(api)

    await api.http.delete(f"/api/sessions/{first['id']}", params={"remove_worktree": True})
    kept = path.is_dir()
    await api.http.delete(f"/api/sessions/{second['id']}", params={"remove_worktree": True})

    assert kept
    assert not path.exists()
    assert local_branches(repo_of(tmp_path)) == ["feat", "main"]


async def test_an_archived_chat_keeps_its_shared_worktree(api: Api, tmp_path: Path) -> None:
    first, second, path = await pair(api)
    await api.http.patch(f"/api/sessions/{second['id']}", json={"archived": True})

    await api.http.delete(f"/api/sessions/{first['id']}", params={"remove_worktree": True})

    assert path.is_dir()
    assert local_branches(repo_of(tmp_path)) == ["feat", "main"]


async def test_purging_removes_a_shared_worktree_only_with_its_last_chat(
    api: Api, tmp_path: Path
) -> None:
    first, second, path = await pair(api)

    await api.http.delete(f"/api/sessions/{second['id']}", params={"purge": True})
    kept = path.is_dir()
    await api.http.delete(f"/api/sessions/{first['id']}", params={"purge": True})

    assert kept
    assert not path.exists()
    assert local_branches(repo_of(tmp_path)) == ["feat", "main"]


async def test_closing_keeping_work_keeps_a_shared_worktree(api: Api, tmp_path: Path) -> None:
    first, second, path = await pair(api)

    kept = await api.ctx.sessions.close_keeping_work(str(first["id"]))
    still = path.is_dir()
    last = await api.ctx.sessions.close_keeping_work(str(second["id"]))

    assert (kept, still) == (True, True)
    assert not last
    assert not path.exists()


async def test_removing_the_repo_with_its_chats_removes_their_shared_worktree(
    api: Api, tmp_path: Path
) -> None:
    _, _, path = await pair(api)

    response = await api.http.delete("/api/repos/repo", params={"purge_sessions": True})

    assert response.status_code == 204
    assert not path.exists()
    assert local_branches(repo_of(tmp_path)) == ["feat", "main"]


async def test_chats_deleted_together_do_not_keep_their_shared_worktree(api: Api) -> None:
    first, second, path = await pair(api)

    await api.ctx.sessions.purge(str(second["id"]), along_with={str(first["id"])})

    assert not path.exists()


@pytest.mark.parametrize("delete", [{"remove_worktree": True}, {"purge": True}])
async def test_worktrees_nest_did_not_make_are_never_removed(
    api: Api, tmp_path: Path, delete: dict[str, bool]
) -> None:
    repo = repo_of(tmp_path)
    claude = add_worktree(repo, repo / ".claude" / "worktrees" / "brave-otter", "cc-x")
    other = add_worktree(repo, tmp_path / "elsewhere", "side")
    chats = [await started(api, worktree_path=str(path)) for path in (claude, other)]

    for chat in chats:
        response = await api.http.delete(f"/api/sessions/{chat['id']}", params=delete)
        assert response.status_code in (200, 204)

    assert claude.is_dir()
    assert other.is_dir()
    assert local_branches(repo) == ["cc-x", "main", "side"]


async def test_a_foreign_worktree_with_no_work_is_kept_on_close(api: Api, tmp_path: Path) -> None:
    path = add_worktree(repo_of(tmp_path), tmp_path / "elsewhere", "side")
    joined = await started(api, worktree_path=str(path))

    kept = await api.ctx.sessions.close_keeping_work(str(joined["id"]))

    assert kept
    assert path.is_dir()
