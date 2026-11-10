"""File checkpoints as git snapshots restore what any tool or command changed (B145)."""

import asyncio
import os
import subprocess
import time
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


async def test_restore_keeps_files_the_snapshot_ignored_when_gitignore_went(
    repo: Path,
) -> None:
    """B159 R01: undoing a turn that removed `.gitignore` must not delete `.env`."""
    (repo / ".gitignore").write_text("build/\n.env\n", encoding="utf-8")
    git(repo, "commit", "-q", "-am", "ignore .env")
    (repo / ".env").write_text("SECRET=1\n", encoding="utf-8")
    (repo / "build").mkdir()
    (repo / "build" / "cache.db").write_text("local data\n", encoding="utf-8")
    commit = await snapshots.snapshot(repo, "chat/4")
    (repo / ".gitignore").unlink()
    (repo / "made.txt").write_text("the turn made this\n", encoding="utf-8")

    done = await snapshots.restore(repo, commit)

    assert (repo / ".env").read_text(encoding="utf-8") == "SECRET=1\n"
    assert (repo / "build" / "cache.db").read_text(encoding="utf-8") == "local data\n"
    assert (repo / ".gitignore").exists()
    assert not (repo / "made.txt").exists()
    assert {(c.path, c.status) for c in done.changes} == {(".gitignore", "D"), ("made.txt", "A")}


async def test_restore_keeps_a_file_a_new_gitignore_unignored(repo: Path) -> None:
    """B159 recheck 1: a turn's new `sub/.gitignore` with `!.env` must not cost `sub/.env`."""
    (repo / ".gitignore").write_text("build/\n.env\n", encoding="utf-8")
    git(repo, "commit", "-q", "-am", "ignore .env")
    (repo / "sub").mkdir()
    (repo / "sub" / ".env").write_text("SECRET=1\n", encoding="utf-8")
    commit = await snapshots.snapshot(repo, "chat/5")
    (repo / "sub" / ".gitignore").write_text("!.env\n", encoding="utf-8")

    done = await snapshots.restore(repo, commit)

    assert (repo / "sub" / ".env").read_text(encoding="utf-8") == "SECRET=1\n"
    assert not (repo / "sub" / ".gitignore").exists()
    assert {(c.path, c.status) for c in done.changes} == {("sub/.gitignore", "A")}


async def test_restore_keeps_what_the_exclude_file_ignored_and_leaves_that_file(
    repo: Path,
) -> None:
    exclude = repo / ".git" / "info" / "exclude"
    exclude.parent.mkdir(exist_ok=True)
    exclude.write_text(".env\n", encoding="utf-8")
    (repo / ".env").write_text("SECRET=1\n", encoding="utf-8")
    commit = await snapshots.snapshot(repo, "chat/6")
    exclude.write_text("", encoding="utf-8")

    done = await snapshots.restore(repo, commit)

    assert (repo / ".env").read_text(encoding="utf-8") == "SECRET=1\n"
    assert exclude.read_text(encoding="utf-8") == ""
    assert done.changes == []


async def test_restore_keeps_a_file_a_self_ignoring_new_gitignore_unignored(
    repo: Path,
) -> None:
    """B159 recheck 2 A: the new `sub/.gitignore` ignores itself, so it is never deleted."""
    (repo / ".gitignore").write_text("build/\n.env\n", encoding="utf-8")
    git(repo, "commit", "-q", "-am", "ignore .env")
    (repo / "sub").mkdir()
    (repo / "sub" / ".env").write_text("SECRET=1\n", encoding="utf-8")
    commit = await snapshots.snapshot(repo, "chat/7")
    (repo / "sub" / ".gitignore").write_text("!.env\n.gitignore\n", encoding="utf-8")

    done = await snapshots.restore(repo, commit)

    assert (repo / "sub" / ".env").read_text(encoding="utf-8") == "SECRET=1\n"
    assert done.changes == []


async def test_restore_keeps_a_file_unignored_by_a_new_gitignore_the_root_ignores(
    repo: Path,
) -> None:
    """B159 recheck 2 A: a force-added `sub/.gitignore` the root ignores is kept as ignored."""
    (repo / ".gitignore").write_text("build/\n.env\n", encoding="utf-8")
    git(repo, "commit", "-q", "-am", "ignore .env")
    (repo / "sub").mkdir()
    (repo / "sub" / ".env").write_text("SECRET=1\n", encoding="utf-8")
    commit = await snapshots.snapshot(repo, "chat/8")
    (repo / "sub" / ".gitignore").write_text("!.env\n", encoding="utf-8")
    (repo / ".gitignore").write_text("build/\n.env\nsub/.gitignore\n", encoding="utf-8")
    git(repo, "add", "-f", "sub/.gitignore")

    done = await snapshots.restore(repo, commit)

    assert (repo / "sub" / ".env").read_text(encoding="utf-8") == "SECRET=1\n"
    assert (repo / ".gitignore").read_text(encoding="utf-8") == "build/\n.env\n"
    assert {(c.path, c.status) for c in done.changes} == {(".gitignore", "M")}


async def test_restore_keeps_what_the_excludes_file_ignored_before_the_turn_changed_it(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """B159 recheck 2 A: `git config core.excludesFile /dev/null` cost the user `.env`."""
    ignore = tmp_path / "global-ignore"
    ignore.write_text(".env\n", encoding="utf-8")
    config = tmp_path / "gitconfig"
    config.write_text(f"[core]\n\texcludesFile = {ignore}\n", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    (repo / ".env").write_text("SECRET=1\n", encoding="utf-8")
    commit = await snapshots.snapshot(repo, "chat/9")
    git(repo, "config", "core.excludesFile", os.devnull)

    done = await snapshots.restore(repo, commit)

    assert (repo / ".env").read_text(encoding="utf-8") == "SECRET=1\n"
    assert done.changes == []


async def test_restore_leaves_lines_added_to_the_exclude_file_since(repo: Path) -> None:
    """B159 recheck 2 B: a rewind dropped Nest's worktrees line, so main saw the worktrees."""
    commit = await snapshots.snapshot(repo, "chat/12")
    exclude = repo / ".git" / "info" / "exclude"
    exclude.parent.mkdir(exist_ok=True)
    exclude.write_text("/.worktrees/\n", encoding="utf-8")
    (repo / ".worktrees" / "one").mkdir(parents=True)
    (repo / ".worktrees" / "one" / "file.txt").write_text("work\n", encoding="utf-8")

    done = await snapshots.restore(repo, commit)

    assert exclude.read_text(encoding="utf-8") == "/.worktrees/\n"
    assert (repo / ".worktrees" / "one" / "file.txt").exists()
    assert done.changes == []


async def test_restore_keeps_what_an_ignored_gitignore_ignored_before_the_turn_changed_it(
    repo: Path,
) -> None:
    """B159 recheck 3 problem 3: a local-only `sub/.gitignore` that `.git/info/exclude`
    lists lost its `.env` line, and the rewind deleted `sub/.env`."""
    exclude = repo / ".git" / "info" / "exclude"
    exclude.parent.mkdir(exist_ok=True)
    exclude.write_text("sub/.gitignore\n", encoding="utf-8")
    (repo / "sub").mkdir()
    (repo / "sub" / ".gitignore").write_text(".env\n", encoding="utf-8")
    (repo / "sub" / ".env").write_text("SECRET=1\n", encoding="utf-8")
    commit = await snapshots.snapshot(repo, "chat/14")
    (repo / "sub" / ".gitignore").write_text("", encoding="utf-8")

    preview = await snapshots.changes(repo, commit)
    done = await snapshots.restore(repo, commit)

    assert (repo / "sub" / ".env").read_text(encoding="utf-8") == "SECRET=1\n"
    assert preview == done
    assert done.changes == []


async def test_a_snapshot_keeps_no_rule_file_from_outside_the_repository(
    repo: Path, tmp_path: Path
) -> None:
    """B159 recheck 3 problem 4: `core.excludesFile ~/.ssh/id_x` stored the key as a blob."""
    secret = tmp_path / "id_x"
    secret.write_text("PRIVATE KEY\n", encoding="utf-8")
    git(repo, "config", "core.excludesFile", str(secret))
    exclude = repo / ".git" / "info" / "exclude"
    exclude.parent.mkdir(exist_ok=True)
    exclude.unlink(missing_ok=True)
    exclude.symlink_to(secret)
    (repo / "sub").mkdir()
    (repo / "sub" / ".gitignore").symlink_to(secret)
    (repo / ".gitignore").write_text("build/\nsub/.gitignore\n", encoding="utf-8")

    await snapshots.snapshot(repo, "chat/15")

    blob = git(repo, "hash-object", "--", str(secret)).strip()
    with pytest.raises(subprocess.CalledProcessError):
        git(repo, "cat-file", "-e", blob)


async def test_a_snapshot_skips_an_unreadable_exclude_file(repo: Path) -> None:
    """B159 recheck 3 problem 5: an unreadable `.git/info/exclude` failed the snapshot."""
    exclude = repo / ".git" / "info" / "exclude"
    exclude.parent.mkdir(exist_ok=True)
    exclude.write_text("*.log\n", encoding="utf-8")
    exclude.chmod(0)
    try:
        commit = await snapshots.snapshot(repo, "chat/16")
    finally:
        exclude.chmod(0o644)

    (repo / "notes.txt").write_text("changed\n", encoding="utf-8")
    done = await snapshots.restore(repo, commit)
    assert (repo / "notes.txt").read_text(encoding="utf-8") == "one\ntwo\n"
    assert {(c.path, c.status) for c in done.changes} == {("notes.txt", "M")}


async def test_a_snapshot_skips_an_ignored_gitignore_that_is_a_symlink_loop(repo: Path) -> None:
    """B159 recheck 4 problem 1: `Path.resolve()` raised on the loop and failed the snapshot."""
    exclude = repo / ".git" / "info" / "exclude"
    exclude.parent.mkdir(exist_ok=True)
    exclude.write_text("sub/.gitignore\n", encoding="utf-8")
    (repo / "sub").mkdir()
    (repo / "sub" / ".gitignore").symlink_to(".gitignore")

    commit = await snapshots.snapshot(repo, "chat/17")

    (repo / "notes.txt").write_text("changed\n", encoding="utf-8")
    await snapshots.restore(repo, commit)
    assert (repo / "notes.txt").read_text(encoding="utf-8") == "one\ntwo\n"


async def test_a_same_size_edit_in_the_second_the_index_was_written_is_seen(
    repo: Path,
) -> None:
    """B159 recheck 6: the scratch index got a new modification time, so git trusted the
    saved stat of a file edited, at the same size, in the second the index was written.
    The repository settings make git compare whole seconds only, as on a coarse clock.
    """
    git(repo, "config", "core.trustctime", "false")
    git(repo, "config", "core.checkStat", "minimal")
    notes = repo / "notes.txt"
    second = int(time.time()) - 60
    os.utime(notes, (second, second))
    git(repo, "update-index", "--refresh")
    commit = await snapshots.snapshot(repo, "chat/18")

    notes.write_text("changed\n", encoding="utf-8")
    os.utime(notes, (second, second))
    os.utime(repo / ".git" / "index", (second, second))

    assert await snapshots.changed_since(repo, commit) == ["notes.txt"]


async def test_the_preview_lists_what_the_restore_deletes_and_no_more(repo: Path) -> None:
    """B159 recheck 2 C: the preview listed a kept `sub/.env` as a file to delete."""
    (repo / ".gitignore").write_text("build/\n.env\n", encoding="utf-8")
    git(repo, "commit", "-q", "-am", "ignore .env")
    (repo / "sub").mkdir()
    (repo / "sub" / ".env").write_text("SECRET=1\n", encoding="utf-8")
    commit = await snapshots.snapshot(repo, "chat/13")
    (repo / "sub" / ".gitignore").write_text("!.env\n", encoding="utf-8")
    (repo / "made.txt").write_text("the turn made this\n", encoding="utf-8")

    preview = await snapshots.changes(repo, commit)
    done = await snapshots.restore(repo, commit)

    assert preview == done
    assert {(c.path, c.status) for c in done.changes} == {
        ("sub/.gitignore", "A"),
        ("made.txt", "A"),
    }
    assert (repo / "sub" / ".env").exists()


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


async def test_a_folder_inside_a_repository_is_never_snapshotted_or_restored(repo: Path) -> None:
    """B159 R10: a plain folder inside an enclosing repository (General inside a home
    folder kept in git) must not cover that repository, nor undo files outside itself.
    """
    inside = repo / "general"
    inside.mkdir()
    old = await snapshots.snapshot(repo, "chat/14")
    (repo / "outside.txt").write_text("the user's file\n", encoding="utf-8")

    with pytest.raises(GitError):
        await snapshots.snapshot(inside, "chat/15")
    with pytest.raises(GitError):
        # A snapshot from before this check, taken at the enclosing top.
        await snapshots.restore(inside, old)

    assert (repo / "outside.txt").exists()
    assert "chat/15" not in git(repo, "for-each-ref", "refs/nest/")


async def test_a_restore_limited_to_the_chats_paths_leaves_the_rest(repo: Path) -> None:
    """B159 R10: only the paths the chat's own turns changed go back."""
    commit = await snapshots.snapshot(repo, "chat/16")
    (repo / "notes.txt").write_text("the chat's edit\n", encoding="utf-8")
    (repo / "theirs.txt").write_text("another chat's file\n", encoding="utf-8")
    (repo / "draft.txt").write_text("the user's edit\n", encoding="utf-8")
    only = {"notes.txt"}

    preview = await snapshots.changes(repo, commit, only)
    done = await snapshots.restore(repo, commit, only)

    assert preview == done
    assert [c.path for c in done.changes] == ["notes.txt"]
    assert (repo / "notes.txt").read_text(encoding="utf-8") == "one\ntwo\n"
    assert (repo / "theirs.txt").exists()
    assert (repo / "draft.txt").read_text(encoding="utf-8") == "the user's edit\n"
