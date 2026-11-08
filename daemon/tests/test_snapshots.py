"""File checkpoints as git snapshots restore what any tool or command changed (B145)."""

import asyncio
from pathlib import Path

import pytest

from nestd.gitops import snapshots
from nestd.gitops.runner import GitError
from tests.git_support import git, init_repo


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = init_repo(tmp_path / "repo")
    (path / ".gitignore").write_text("build/\n", encoding="utf-8")
    (path / "notes.txt").write_text("one\ntwo\n", encoding="utf-8")
    (path / "draft.txt").write_text("untracked before\n", encoding="utf-8")
    git(path, "add", ".gitignore", "notes.txt")
    git(path, "commit", "-q", "-m", "files")
    return path


async def test_restore_undoes_edits_new_files_deletions_and_shell_changes(repo: Path) -> None:
    commit = await snapshots.snapshot(repo, "chat/1")
    (repo / "notes.txt").write_text("one\nchanged\nthree\n", encoding="utf-8")
    (repo / "README.md").unlink()
    (repo / "src" / "deep").mkdir(parents=True)
    (repo / "src" / "deep" / "new.py").write_text("x = 1\n", encoding="utf-8")
    # A shell command, not an edit tool: Claude Code's own checkpoints miss these.
    shell = await asyncio.create_subprocess_exec("sh", "-c", "echo shell >> draft.txt", cwd=repo)
    assert await shell.wait() == 0

    preview = await snapshots.changes(repo, commit)
    assert {(c.path, c.status) for c in preview.changes} == {
        ("notes.txt", "M"),
        ("README.md", "D"),
        ("src/deep/new.py", "A"),
        ("draft.txt", "M"),
    }
    assert (repo / "src" / "deep" / "new.py").exists()  # a preview changes nothing

    await snapshots.restore(repo, commit)

    assert (repo / "notes.txt").read_text(encoding="utf-8") == "one\ntwo\n"
    assert (repo / "README.md").read_text(encoding="utf-8") == "hello\n"
    assert (repo / "draft.txt").read_text(encoding="utf-8") == "untracked before\n"
    assert not (repo / "src").exists()
    assert (await snapshots.changes(repo, commit)).changes == []


async def test_snapshots_leave_the_users_index_branches_and_ignored_files_alone(
    repo: Path,
) -> None:
    (repo / "notes.txt").write_text("staged\n", encoding="utf-8")
    git(repo, "add", "notes.txt")
    staged = git(repo, "diff", "--cached", "--name-only")
    head = git(repo, "rev-parse", "HEAD")
    (repo / "build").mkdir()
    (repo / "build" / "out.bin").write_text("ignored\n", encoding="utf-8")

    commit = await snapshots.snapshot(repo, "chat/2")
    (repo / "build" / "out.bin").write_text("rebuilt\n", encoding="utf-8")
    await snapshots.restore(repo, commit)

    assert git(repo, "diff", "--cached", "--name-only") == staged
    assert git(repo, "rev-parse", "HEAD") == head
    assert git(repo, "status", "--porcelain", "--untracked-files=no").strip() == "M  notes.txt"
    assert (repo / "build" / "out.bin").read_text(encoding="utf-8") == "rebuilt\n"
    assert git(repo, "stash", "list") == ""


async def test_a_worktree_restores_its_own_files(repo: Path, tmp_path: Path) -> None:
    tree = tmp_path / "tree"
    git(repo, "worktree", "add", "-q", "-b", "work", str(tree))
    commit = await snapshots.snapshot(tree, "chat/3")
    (tree / "notes.txt").write_text("in the worktree\n", encoding="utf-8")

    await snapshots.restore(tree, commit)

    assert (tree / "notes.txt").read_text(encoding="utf-8") == "one\ntwo\n"
    assert git(tree, "status", "--porcelain") == ""
    assert git(repo, "for-each-ref", "--format=%(refname)", "refs/nest/").split() == [
        "refs/nest/checkpoints/chat/3"
    ]


async def test_a_deleted_chats_refs_go(repo: Path) -> None:
    await snapshots.snapshot(repo, "chat/10")
    await snapshots.snapshot(repo, "chat/11")
    await snapshots.snapshot(repo, "other/1")

    await snapshots.forget(repo, "chat")

    refs = git(repo, "for-each-ref", "--format=%(refname)", "refs/nest/").split()
    assert refs == ["refs/nest/checkpoints/other/1"]


async def test_a_plain_folder_has_no_snapshot(tmp_path: Path) -> None:
    with pytest.raises(GitError) as raised:
        await snapshots.snapshot(tmp_path, "chat/1")
    assert raised.value.not_a_repository
