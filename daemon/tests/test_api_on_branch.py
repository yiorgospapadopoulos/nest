"""A new chat working on an existing local branch (B96 round 3): in place on the folder's
branch, in the worktree that has it checked out, or in a new Nest worktree with that branch
checked out. Removing such a worktree never deletes the branch: Nest deletes no branch.
"""

from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path

import pytest

from nestd.events import types
from nestd.gitops.runner import GitError
from nestd.sessions.models import NewSession
from nestd.sessions.workspace import prepare_worktree
from nestd.storage.db import Database
from tests.api_client import Api, running_api
from tests.fakes import FakeClock, FakeSecretStore
from tests.git_support import commit_file, git, init_repo
from tests.session_support import Env
from tests.test_api_join_worktree import (
    add_worktree,
    local_branches,
    refused,
    repo_of,
    started,
    workspace_events,
)


def branch(repo: Path, name: str, start: str = "main") -> str:
    """A new local branch with a commit of its own, the folder staying on its branch;
    returns where it forked.
    """
    back = git(repo, "branch", "--show-current").strip()
    fork_point = git(repo, "rev-parse", start).strip()
    git(repo, "checkout", "-q", "-b", name, start)
    commit_file(repo, f"{name}.txt")
    git(repo, "checkout", "-q", back)
    return fork_point


def gone(path: Path) -> bool:
    return not path.exists()


def nest_worktrees(repo: Path) -> list[Path]:
    folder = repo / ".claude" / "worktrees"
    return sorted(folder.iterdir()) if folder.is_dir() else []


@pytest.fixture
async def api(tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore) -> AsyncIterator[Api]:
    async with running_api(tmp_path, clock, secrets) as running:
        await running.http.post("/api/repos", json={"path": str(init_repo(tmp_path / "repo"))})
        notes = tmp_path / "notes"
        notes.mkdir()
        await running.http.post("/api/repos", json={"path": str(notes)})
        yield running


# Where the chat works


async def test_the_folders_branch_is_worked_on_in_place(api: Api, tmp_path: Path) -> None:
    repo = repo_of(tmp_path)
    head = git(repo, "rev-parse", "HEAD").strip()

    chat = await started(api, on_branch="main", mode="worktree")

    assert chat["mode"] == "in_place"
    assert chat["cwd"] == str(repo)
    assert chat["worktree_path"] is None
    assert chat["base_ref"] == head
    assert nest_worktrees(repo) == []
    assert Path(api.provider.runs[-1].spec.cwd) == repo


async def test_a_branch_checked_out_in_a_worktree_is_joined(api: Api, tmp_path: Path) -> None:
    repo = repo_of(tmp_path)
    await api.http.patch("/api/repos/repo", json={"setup": ["touch setup-ran"]})
    path = add_worktree(repo, repo / ".claude" / "worktrees" / "brave-otter", "cc-x")

    chat = await started(api, on_branch="cc-x")

    assert chat["mode"] == "worktree"
    assert chat["worktree_path"] == str(path)
    assert chat["cwd"] == str(path)
    assert chat["branch"] == "cc-x"
    assert not (path / "setup-ran").exists()
    assert [e["linked"] for e in await workspace_events(api, chat["id"])] == [[]]


async def test_another_branch_gets_a_nest_worktree_with_it_checked_out(
    api: Api, tmp_path: Path
) -> None:
    repo = repo_of(tmp_path)
    (repo / ".env").write_text("SECRET=1\n", encoding="utf-8")
    await api.http.patch("/api/repos/repo", json={"link": [".env"], "setup": ["touch setup-ran"]})
    fork_point = branch(repo, "feat")
    tip = git(repo, "rev-parse", "feat").strip()
    commit_file(repo, "later.txt")

    chat = await started(api, on_branch="feat")

    path = Path(str(chat["worktree_path"]))
    assert nest_worktrees(repo) == [path]
    assert path.name.startswith("nest-")
    assert chat["mode"] == "worktree"
    assert chat["cwd"] == str(path)
    assert chat["branch"] == "feat"
    assert chat["base_ref"] == fork_point
    assert git(path, "rev-parse", "--abbrev-ref", "HEAD").strip() == "feat"
    assert git(path, "rev-parse", "HEAD").strip() == tip
    assert (path / ".env").is_symlink()
    assert (path / "setup-ran").exists()
    assert local_branches(repo) == ["feat", "main"]
    assert Path(api.provider.runs[-1].spec.cwd) == path
    events = await workspace_events(api, chat["id"])
    assert [(e["path"], e["branch"], e["linked"]) for e in events] == [
        (str(path), "feat", [".env"])
    ]


async def test_the_default_branch_is_based_on_its_own_commit(api: Api, tmp_path: Path) -> None:
    """The folder is on another branch; the default branch is the map's root."""
    repo = repo_of(tmp_path)
    tip = git(repo, "rev-parse", "main").strip()
    git(repo, "checkout", "-q", "-b", "wip")
    commit_file(repo, "wip.txt")

    chat = await started(api, on_branch="main")

    assert chat["mode"] == "worktree"
    assert chat["branch"] == "main"
    assert chat["base_ref"] == tip
    assert git(repo, "branch", "--show-current").strip() == "wip"


async def test_without_a_default_branch_the_base_is_the_branchs_commit(
    api: Api, tmp_path: Path
) -> None:
    repo = repo_of(tmp_path)
    git(repo, "checkout", "-q", "-b", "aaa")
    git(repo, "branch", "-D", "main")
    git(repo, "branch", "bbb")
    tip = commit_file(repo, "a.txt")
    git(repo, "branch", "-f", "bbb", tip)
    git(repo, "checkout", "-q", "--detach")

    chat = await started(api, on_branch="bbb")

    assert chat["base_ref"] == tip


async def test_a_second_chat_on_the_branch_joins_the_first_ones_worktree(
    api: Api, tmp_path: Path
) -> None:
    repo = repo_of(tmp_path)
    branch(repo, "feat")
    first = await started(api, on_branch="feat")

    second = await started(api, on_branch="feat")

    assert second["worktree_path"] == first["worktree_path"]
    assert second["base_ref"] == first["base_ref"]
    assert len(nest_worktrees(repo)) == 1


# Refused


async def test_a_plain_folder_has_no_branches(api: Api) -> None:
    detail = await refused(api, "notes", on_branch="main")

    assert detail == {"detail": "notes is not a git repository, so it has no branches"}


@pytest.mark.parametrize("name", ["nope", "-x", "main~1", "origin/main"])
async def test_only_a_local_branch_is_taken(api: Api, name: str) -> None:
    detail = await refused(api, on_branch=name)

    assert detail == {"detail": f"repo has no local branch named {name!r}"}


@pytest.mark.parametrize(
    "fields",
    [{"branch": "x"}, {"base": "main"}, {"worktree_path": "/abs/x"}, {"mode": "in_place"}],
)
async def test_working_on_a_branch_takes_no_other_place(
    api: Api, tmp_path: Path, fields: dict[str, str]
) -> None:
    branch(repo_of(tmp_path), "feat")

    detail = await refused(api, on_branch="feat", **fields)

    assert detail == {
        "detail": "a chat on a branch takes no branch, base, worktree_path or in-place mode"
    }


# The branch is never deleted


async def remove_close(api: Api, chat: dict[str, object]) -> None:
    await api.http.delete(f"/api/sessions/{chat['id']}", params={"remove_worktree": True})


async def remove_purge(api: Api, chat: dict[str, object]) -> None:
    await api.http.delete(f"/api/sessions/{chat['id']}", params={"purge": True})


async def remove_keeping_work(api: Api, chat: dict[str, object]) -> None:
    assert not await api.ctx.sessions.close_keeping_work(str(chat["id"]))


async def remove_repo(api: Api, chat: dict[str, object]) -> None:
    del chat
    response = await api.http.delete("/api/repos/repo", params={"purge_sessions": True})
    assert response.status_code == 204


@pytest.mark.parametrize("remove", [remove_close, remove_purge, remove_keeping_work, remove_repo])
async def test_removing_the_worktree_keeps_the_branch(
    api: Api, tmp_path: Path, remove: Callable[[Api, dict[str, object]], Awaitable[None]]
) -> None:
    """The branch has no commits of its own, so its worktree holds no work either."""
    repo = repo_of(tmp_path)
    git(repo, "branch", "feat")
    tip = git(repo, "rev-parse", "feat").strip()
    chat = await started(api, on_branch="feat")
    path = Path(str(chat["worktree_path"]))

    await remove(api, chat)

    assert gone(path)
    assert local_branches(repo) == ["feat", "main"]
    assert git(repo, "rev-parse", "feat").strip() == tip


async def test_chats_that_joined_keep_the_branch_too(api: Api, tmp_path: Path) -> None:
    repo = repo_of(tmp_path)
    branch(repo, "feat")
    first = await started(api, on_branch="feat")
    path = Path(str(first["worktree_path"]))
    second = await started(api, worktree_path=str(path))
    third = await started(api, on_branch="feat")
    await remove_purge(api, first)
    await remove_close(api, second)
    kept = not gone(path)

    await remove_close(api, third)

    assert kept
    assert gone(path)
    assert local_branches(repo) == ["feat", "main"]


async def test_a_nest_worktree_no_chat_recorded_keeps_its_branch(api: Api, tmp_path: Path) -> None:
    repo = repo_of(tmp_path)
    path = add_worktree(repo, repo / ".claude" / "worktrees" / "nest-0badc0de", "found")
    chat = await started(api, worktree_path=str(path))

    await remove_close(api, chat)

    assert gone(path)
    assert local_branches(repo) == ["found", "main"]


@pytest.mark.parametrize("remove", [remove_close, remove_purge, remove_keeping_work, remove_repo])
async def test_nests_own_branch_is_kept_too(
    api: Api, tmp_path: Path, remove: Callable[[Api, dict[str, object]], Awaitable[None]]
) -> None:
    """Even the branches Nest makes for its worktrees stay (round 4)."""
    repo = repo_of(tmp_path)
    chat = await started(api, mode="worktree", branch="feat")
    generated = await started(api, mode="worktree")
    paths = [Path(str(c["worktree_path"])) for c in (chat, generated)]

    # Removing the project removes both chats at once.
    for each in [chat] if remove is remove_repo else [chat, generated]:
        await remove(api, each)

    assert all(gone(path) for path in paths)
    assert local_branches(repo) == sorted(["feat", "main", str(generated["branch"])])


# A worktree made for the branch meanwhile


@pytest.fixture
async def env(tmp_path: Path, db: Database, clock: FakeClock) -> AsyncIterator[Env]:
    yield (environment := Env(tmp_path, db, clock))
    await environment.manager.shutdown()


async def test_a_chat_whose_branch_got_a_worktree_meanwhile_joins_it(env: Env) -> None:
    await env.register()
    repo = env.repos.get("repo")
    base = git(env.repo_path, "rev-parse", "main").strip()
    git(env.repo_path, "branch", "feat")
    session = await env.store.create(
        NewSession(
            repo="repo",
            title="t",
            prompt="p",
            mode="worktree",
            cwd=None,
            model=None,
            effort=None,
            permission_mode="default",
            provider="claude",
            base_ref=base,
        ),
        branch="feat",
    )
    path = env.repo_path.parent / "meanwhile"
    git(env.repo_path, "worktree", "add", "-q", str(path), "feat")

    setup = await prepare_worktree(session, repo, env.worktrees, env.store, env.bus)

    assert setup is None
    after = await env.store.get(session.id)
    assert after.worktree_path == path.resolve()
    assert after.cwd == path.resolve()
    assert after.base_ref == base
    workspace = [
        e.payload
        for e in await env.bus.session_events(session.id)
        if e.type == types.SESSION_WORKSPACE
    ]
    assert [(w["path"], w["linked"]) for w in workspace] == [(str(path.resolve()), [])]


async def test_a_branch_the_folder_switched_to_meanwhile_fails_to_check_out(env: Env) -> None:
    """git refuses a branch checked out in the project folder, and there is no worktree
    of it to join.
    """
    await env.register()
    repo = env.repos.get("repo")
    base = git(env.repo_path, "rev-parse", "main").strip()
    git(env.repo_path, "checkout", "-q", "-b", "feat")
    session = await env.store.create(
        NewSession(
            repo="repo",
            title="t",
            prompt="p",
            mode="worktree",
            cwd=None,
            model=None,
            effort=None,
            permission_mode="default",
            provider="claude",
            base_ref=base,
        ),
        branch="feat",
    )

    with pytest.raises(GitError):
        await prepare_worktree(session, repo, env.worktrees, env.store, env.bus)

    assert (await env.store.get(session.id)).worktree_path is None
