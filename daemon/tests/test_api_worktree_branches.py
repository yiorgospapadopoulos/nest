"""Where a chat works (B55): the checked-out branch, local branches, and a worktree chat
started from a chosen branch under a chosen name.
"""

import shutil
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

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


def local_branches(repo: Path) -> list[str]:
    return git(repo, "branch", "--format=%(refname:short)").split()


async def current_branch(api: Api, name: str = "repo") -> object:
    return (await api.http.get(f"/api/repos/{name}")).json()["current_branch"]


async def test_the_repo_payload_reports_the_branch_checked_out_now(
    api: Api, tmp_path: Path
) -> None:
    repo = tmp_path / "repo"

    first = await current_branch(api)
    git(repo, "checkout", "-q", "-b", "fix/login")
    switched = await current_branch(api)
    listed = {r["name"]: r["current_branch"] for r in (await api.http.get("/api/repos")).json()}
    git(repo, "checkout", "-q", "--detach")
    detached = await current_branch(api)

    assert (first, switched, detached) == ("main", "fix/login", None)
    assert listed == {"repo": "fix/login", "notes": None}
    assert (await api.http.get("/api/repos/repo")).json()["default_branch"] == "main"


async def test_a_repo_without_commits_or_without_its_folder_has_no_current_branch(
    api: Api, tmp_path: Path
) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    git(empty, "init", "-q", "-b", "main")

    registered = await api.http.post("/api/repos", json={"path": str(empty)})
    shutil.rmtree(tmp_path / "repo")

    assert registered.json()["current_branch"] is None
    assert await current_branch(api) is None


async def test_branches_lists_local_branches_sorted(api: Api, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    git(repo, "branch", "zeta")
    git(repo, "branch", "fix/login")
    git(repo, "tag", "zeta-tag")

    response = await api.http.get("/api/repos/repo/branches")

    assert response.status_code == 200
    assert response.json() == {"branches": ["fix/login", "main", "zeta"]}


async def test_branches_of_an_unknown_repo_a_plain_folder_or_a_missing_folder(
    api: Api, tmp_path: Path
) -> None:
    unknown = await api.http.get("/api/repos/nope/branches")
    plain = await api.http.get("/api/repos/notes/branches")
    shutil.rmtree(tmp_path / "repo")
    missing = await api.http.get("/api/repos/repo/branches")

    assert (unknown.status_code, unknown.json()) == (404, {"detail": "unknown repo 'nope'"})
    assert (plain.status_code, plain.json()) == (409, NOT_GIT)
    assert missing.status_code == 409
    assert "no longer exists" in missing.json()["detail"]


async def start(api: Api, **fields: object) -> dict[str, object]:
    response = await api.http.post(
        "/api/sessions", json={"repo": "repo", "prompt": "Do it", "mode": "worktree", **fields}
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_a_worktree_chat_gets_the_branch_name_asked_for_from_the_base_asked_for(
    api: Api, tmp_path: Path
) -> None:
    repo = tmp_path / "repo"
    git(repo, "checkout", "-q", "-b", "feature")
    feature = commit_file(repo, "feature.txt")
    git(repo, "checkout", "-q", "main")
    api.provider.script(reply("Done"))

    session = await start(api, branch="fix/login", base="feature")
    await reach(api, str(session["id"]), "idle", results=1)
    stored = (await api.http.get(f"/api/sessions/{session['id']}")).json()
    worktree = Path(stored["worktree_path"])

    assert session["branch"] == "fix/login"
    assert stored["branch"] == "fix/login"
    assert stored["base_ref"] == feature
    assert worktree.name == f"nest-{str(session['id'])[:8]}"
    assert git(worktree, "rev-parse", "--abbrev-ref", "HEAD").strip() == "fix/login"
    assert (worktree / "feature.txt").is_file()


async def test_without_a_base_the_worktree_starts_from_the_default_branch(
    api: Api, tmp_path: Path
) -> None:
    repo = tmp_path / "repo"
    main = git(repo, "rev-parse", "main").strip()
    git(repo, "checkout", "-q", "-b", "other")
    commit_file(repo, "other.txt")
    api.provider.script(reply("Done"))

    session = await start(api, branch="mine")
    await reach(api, str(session["id"]), "idle", results=1)
    stored = (await api.http.get(f"/api/sessions/{session['id']}")).json()

    assert stored["base_ref"] == main
    assert not (Path(stored["worktree_path"]) / "other.txt").exists()


async def test_a_custom_branch_is_kept_when_its_worktree_is_removed(
    api: Api, tmp_path: Path
) -> None:
    repo = tmp_path / "repo"
    api.provider.script(reply("Done"), reply("Done"))
    closed = await start(api, branch="closed-one")
    purged = await start(api, branch="purged-one")
    for session in (closed, purged):
        await reach(api, str(session["id"]), "idle", results=1)
    paths = [
        Path((await api.http.get(f"/api/sessions/{s['id']}")).json()["worktree_path"])
        for s in (closed, purged)
    ]

    await api.http.delete(f"/api/sessions/{closed['id']}", params={"remove_worktree": True})
    await api.http.delete(f"/api/sessions/{purged['id']}", params={"purge": True})
    await until(lambda: not any(path.exists() for path in paths))

    assert local_branches(repo) == ["closed-one", "main", "purged-one"]


@pytest.mark.parametrize("name", ["-x", "bad..name", "has space", "@{-1}", "HEAD", "end/", ""])
async def test_an_invalid_branch_name_is_refused(api: Api, name: str) -> None:
    response = await api.http.post(
        "/api/sessions",
        json={"repo": "repo", "prompt": "x", "mode": "worktree", "branch": name},
    )

    assert response.status_code == 422
    assert (await api.http.get("/api/sessions")).json() == []


async def test_an_existing_branch_name_is_a_conflict(api: Api, tmp_path: Path) -> None:
    git(tmp_path / "repo", "branch", "taken")

    response = await api.http.post(
        "/api/sessions",
        json={"repo": "repo", "prompt": "x", "mode": "worktree", "branch": "taken"},
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "a branch named 'taken' already exists in repo"}
    assert (await api.http.get("/api/sessions")).json() == []


async def test_a_base_that_is_not_a_local_branch_is_refused(api: Api, tmp_path: Path) -> None:
    git(tmp_path / "repo", "tag", "v1")

    responses = [
        await api.http.post(
            "/api/sessions",
            json={"repo": "repo", "prompt": "x", "mode": "worktree", "base": base},
        )
        for base in ("nope", "v1", "-x")
    ]

    assert [r.status_code for r in responses] == [422, 422, 422]
    assert responses[0].json() == {"detail": "repo has no local branch named 'nope'"}


@pytest.mark.parametrize(
    ("repo", "fields"),
    [
        ("repo", {"mode": "in_place", "branch": "x"}),
        ("repo", {"mode": "in_place", "base": "main"}),
        ("notes", {"mode": "worktree", "branch": "x"}),
        ("notes", {"base": "main"}),
    ],
)
async def test_branch_and_base_need_a_worktree_chat(
    api: Api, repo: str, fields: dict[str, object]
) -> None:
    response = await api.http.post("/api/sessions", json={"repo": repo, "prompt": "x", **fields})

    assert response.status_code == 422
    assert response.json() == {"detail": "a branch and a base are only for a new worktree chat"}


async def test_a_name_git_would_expand_to_another_branch_is_refused(
    api: Api, tmp_path: Path
) -> None:
    repo = tmp_path / "repo"
    git(repo, "checkout", "-q", "-b", "previous")
    git(repo, "checkout", "-q", "main")

    response = await api.http.post(
        "/api/sessions",
        json={"repo": "repo", "prompt": "x", "mode": "worktree", "branch": "@{-1}"},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "'@{-1}' is not a valid branch name"}
