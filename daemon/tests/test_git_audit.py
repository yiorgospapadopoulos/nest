from collections.abc import Sequence
from pathlib import Path

import pytest

from nestd.gitops.runner import GitError
from nestd.sessions import git_audit
from nestd.sessions.git_audit import HEAD_BRANCH, changed_refs, snapshot_refs
from tests.git_support import commit_file, git, init_repo


async def test_snapshot_lists_refs_and_head(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    git(repo, "tag", "v1")
    head = git(repo, "rev-parse", "HEAD").strip()

    assert await snapshot_refs(repo) == {
        "HEAD": head,
        HEAD_BRANCH: "refs/heads/main",
        "refs/heads/main": head,
        "refs/tags/v1": head,
    }


async def test_a_branch_switch_on_the_same_commit_is_a_change(tmp_path: Path) -> None:
    """SEC-06: a push goes to the branch HEAD names, so the name is audited too."""
    repo = init_repo(tmp_path / "repo")
    git(repo, "branch", "deploy")
    before = await snapshot_refs(repo)
    git(repo, "symbolic-ref", "HEAD", "refs/heads/deploy")

    changes = changed_refs(before, await snapshot_refs(repo))

    assert changes == [
        {"ref": HEAD_BRANCH, "before": "refs/heads/main", "after": "refs/heads/deploy"}
    ]


async def test_a_detached_head_names_no_branch(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    git(repo, "checkout", "-q", "--detach")

    assert HEAD_BRANCH not in await snapshot_refs(repo)


async def test_snapshot_of_a_repo_without_commits(tmp_path: Path) -> None:
    repo = tmp_path / "empty"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")

    assert await snapshot_refs(repo) == {HEAD_BRANCH: "refs/heads/main"}


async def test_snapshot_of_a_plain_folder_is_empty(tmp_path: Path) -> None:
    assert await snapshot_refs(tmp_path) == {}


async def test_snapshot_reports_other_git_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def failing(args: Sequence[str], cwd: Path) -> str:
        raise GitError(args, 128, "fatal: bad object refs/heads/x")

    monkeypatch.setattr(git_audit, "run_hardened_git", failing)

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

    assert refs == {
        "HEAD": new,
        HEAD_BRANCH: "refs/heads/main",
        "refs/heads/main": new,
        "refs/remotes/origin/main": new,
    }
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

    # The detached HEAD was not the daemon's doing: the next audit still reports it.
    assert refs == {
        "HEAD": new,
        HEAD_BRANCH: "refs/heads/main",
        "refs/heads/main": baseline["refs/heads/main"],
    }


async def test_without_a_baseline_the_refs_as_they_are_become_one(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    git(repo, "branch", "other")

    assert await git_audit.with_own_changes(repo, None, "origin") == await snapshot_refs(repo)


def test_only_head_and_its_branch_are_taken_for_a_publish() -> None:
    """BUG-51: a publish uses HEAD's commit, the branch HEAD names and that branch; other
    chats' branches and the user's own keep their baseline values, so they raise nothing.
    """
    baseline = {
        "HEAD": "a",
        HEAD_BRANCH: "refs/heads/main",
        "refs/heads/main": "a",
        "refs/heads/other-chat": "a",
        "refs/remotes/origin/main": "a",
        "refs/tags/v1": "a",
    }
    after = {
        "HEAD": "b",
        HEAD_BRANCH: "refs/heads/feature",
        "refs/heads/main": "b",
        "refs/heads/feature": "b",
        "refs/heads/new-chat": "b",
        "refs/remotes/origin/main": "b",
        "refs/tags/v2": "b",
    }

    refs = git_audit.for_publish(baseline, after)

    assert refs == {
        "HEAD": "b",
        HEAD_BRANCH: "refs/heads/feature",
        "refs/heads/main": "a",
        "refs/heads/feature": "b",
        "refs/heads/other-chat": "a",
        "refs/remotes/origin/main": "a",
        "refs/tags/v1": "a",
    }


def test_a_detached_head_takes_only_head_for_a_publish() -> None:
    baseline = {"HEAD": "a", HEAD_BRANCH: "refs/heads/main", "refs/heads/main": "a"}

    refs = git_audit.for_publish(baseline, {"HEAD": "b", "refs/heads/main": "b"})

    assert refs == {"HEAD": "b", "refs/heads/main": "a"}
