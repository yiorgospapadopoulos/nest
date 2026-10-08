from collections.abc import Sequence
from pathlib import Path

import pytest

from harness.gitops.runner import GitError
from harness.sessions import git_audit
from harness.sessions.git_audit import changed_refs, snapshot_refs
from tests.git_support import commit_file, git, init_repo


async def test_snapshot_lists_refs_and_head(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    git(repo, "tag", "v1")
    head = git(repo, "rev-parse", "HEAD").strip()

    assert await snapshot_refs(repo) == {
        "HEAD": head,
        "refs/heads/main": head,
        "refs/tags/v1": head,
    }


async def test_snapshot_of_a_repo_without_commits(tmp_path: Path) -> None:
    repo = tmp_path / "empty"
    repo.mkdir()
    git(repo, "init", "-q")

    assert await snapshot_refs(repo) == {}


async def test_snapshot_of_a_plain_folder_is_empty(tmp_path: Path) -> None:
    assert await snapshot_refs(tmp_path) == {}


async def test_snapshot_reports_other_git_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def failing(args: Sequence[str], cwd: Path) -> str:
        raise GitError(args, 128, "fatal: bad object refs/heads/x")

    monkeypatch.setattr(git_audit, "run_git", failing)

    with pytest.raises(GitError, match="bad object"):
        await snapshot_refs(tmp_path)


async def test_changed_refs_reports_added_moved_and_deleted_refs(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    git(repo, "branch", "doomed")
    before = await snapshot_refs(repo)
    old = before["HEAD"]
    new = commit_file(repo, "a.txt")
    git(repo, "branch", "-D", "doomed")
    git(repo, "branch", "fresh")

    changes = changed_refs(before, await snapshot_refs(repo))

    assert changes == [
        {"ref": "HEAD", "before": old, "after": new},
        {"ref": "refs/heads/doomed", "before": old, "after": None},
        {"ref": "refs/heads/fresh", "before": None, "after": new},
        {"ref": "refs/heads/main", "before": old, "after": new},
    ]
    assert changed_refs(before, before) == []


async def test_the_daemons_own_commit_and_push_join_the_baseline(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    baseline = await snapshot_refs(repo)
    old = baseline["HEAD"]
    new = commit_file(repo, "a.txt")  # the daemon commits and pushes
    git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    git(repo, "branch", "sneaky")  # meanwhile, a command of the agent

    refs = await git_audit.with_own_changes(repo, baseline, "origin")

    assert refs == {"HEAD": new, "refs/heads/main": new, "refs/remotes/origin/main": new}
    assert changed_refs(refs, await snapshot_refs(repo)) == [
        {"ref": "refs/heads/sneaky", "before": None, "after": new}
    ]
    assert old != new


async def test_on_a_detached_head_only_head_joins_the_baseline(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    baseline = await snapshot_refs(repo)
    git(repo, "checkout", "-q", "--detach")
    new = commit_file(repo, "a.txt")

    refs = await git_audit.with_own_changes(repo, baseline, "origin")

    assert refs == {"HEAD": new, "refs/heads/main": baseline["refs/heads/main"]}


async def test_without_a_baseline_the_refs_as_they_are_become_one(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    git(repo, "branch", "other")

    assert await git_audit.with_own_changes(repo, None, "origin") == await snapshot_refs(repo)


def test_only_head_and_local_branches_are_taken_for_a_publish() -> None:
    baseline = {
        "HEAD": "a",
        "refs/heads/main": "a",
        "refs/heads/gone": "a",
        "refs/remotes/origin/main": "a",
        "refs/tags/v1": "a",
    }
    after = {
        "HEAD": "b",
        "refs/heads/main": "b",
        "refs/heads/new": "b",
        "refs/remotes/origin/main": "b",
        "refs/tags/v2": "b",
    }

    refs = git_audit.with_branches(baseline, after)

    assert refs == {
        "HEAD": "b",
        "refs/heads/main": "b",
        "refs/heads/new": "b",
        "refs/remotes/origin/main": "a",
        "refs/tags/v1": "a",
    }
