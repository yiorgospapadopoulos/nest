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
