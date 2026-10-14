import asyncio
import os
import re
import shutil
from pathlib import Path

import pytest

from harness.config.models import RepoConfig, WorktreeConfig
from harness.gitops.runner import GitError
from harness.paths import AppPaths
from harness.worktrees.manager import Worktree, WorktreeManager, branch_name
from harness.worktrees.setup import run_commands
from tests.async_support import until
from tests.git_support import commit_file, git, init_repo


@pytest.fixture
def paths(tmp_path: Path) -> AppPaths:
    result = AppPaths(config_dir=tmp_path / "config", data_dir=tmp_path / "data")
    result.ensure()
    return result


@pytest.fixture
def manager(paths: AppPaths) -> WorktreeManager:
    return WorktreeManager(paths)


def make_repo(tmp_path: Path, worktree: WorktreeConfig | None = None) -> RepoConfig:
    path = init_repo(tmp_path / "repo")
    return RepoConfig(name="repo", path=path, worktree=worktree or WorktreeConfig())


def branches(repo: RepoConfig) -> list[str]:
    return git(repo.path, "branch", "--format=%(refname:short)").split()


async def test_create_branches_from_the_default_branch_into_the_repos_claude_worktrees(
    manager: WorktreeManager, tmp_path: Path
) -> None:
    repo = make_repo(tmp_path)
    main_sha = git(repo.path, "rev-parse", "main").strip()
    git(repo.path, "checkout", "-q", "-b", "other")
    commit_file(repo.path, "other.txt")

    worktree = await manager.create(repo, "0123456789abcdef", "Fix the login bug!")

    assert worktree.path == repo.path / ".claude" / "worktrees" / "harness-01234567"
    assert re.fullmatch(r"agent/fix-the-login-bug-[0-9a-f]{6}", worktree.branch)
    assert worktree.base_ref == main_sha
    assert (worktree.path / "README.md").is_file()
    assert not (worktree.path / "other.txt").exists()
    assert git(worktree.path, "rev-parse", "--abbrev-ref", "HEAD").strip() == worktree.branch
    assert worktree.branch in branches(repo)


async def test_create_excludes_the_worktrees_from_git_once(
    manager: WorktreeManager, tmp_path: Path
) -> None:
    repo = make_repo(tmp_path)
    exclude = repo.path / ".git" / "info" / "exclude"
    exclude.write_text("# mine\n*.log", encoding="utf-8")

    await manager.create(repo, "aaaaaaaa", "one")
    await manager.create(repo, "bbbbbbbb", "two")

    assert exclude.read_text(encoding="utf-8") == "# mine\n*.log\n/.claude/worktrees/\n"
    assert git(repo.path, "status", "--porcelain") == ""


async def test_create_writes_a_missing_exclude_file(
    manager: WorktreeManager, tmp_path: Path
) -> None:
    repo = make_repo(tmp_path)
    shutil.rmtree(repo.path / ".git" / "info")

    await manager.create(repo, "aaaaaaaa", "one")

    exclude = repo.path / ".git" / "info" / "exclude"
    assert exclude.read_text(encoding="utf-8") == "/.claude/worktrees/\n"


async def test_create_keeps_an_exclude_line_that_is_already_there(
    manager: WorktreeManager, tmp_path: Path
) -> None:
    repo = make_repo(tmp_path)
    exclude = repo.path / ".git" / "info" / "exclude"
    exclude.write_text("  /.claude/worktrees/  \n", encoding="utf-8")

    await manager.create(repo, "aaaaaaaa", "one")

    assert exclude.read_text(encoding="utf-8") == "  /.claude/worktrees/  \n"


async def test_create_falls_back_to_head_without_the_default_branch(
    manager: WorktreeManager, tmp_path: Path
) -> None:
    repo = make_repo(tmp_path).model_copy(update={"default_branch": "missing"})
    head = git(repo.path, "rev-parse", "HEAD").strip()

    worktree = await manager.create(repo, "abcdef0123", "x")

    assert worktree.base_ref == head


async def test_create_reports_git_failures(manager: WorktreeManager, tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    await manager.create(repo, "same-id-1", "a")

    with pytest.raises(GitError):
        await manager.create(repo, "same-id-2", "b")


@pytest.mark.parametrize(
    ("title", "slug"),
    [
        ("!!!", "task"),
        ("Ünïcode ok", "n-code-ok"),
        ("a" * 60, "a" * 40),
        ("x " * 30, "x-" * 19 + "x"),
        (
            "Fix the login redirect after the token expires quickly",
            "fix-the-login-redirect-after-the-token",
        ),
        ("a" * 39 + " bc", "a" * 39),
        ("a" * 40 + " bc", "a" * 40),
    ],
)
def test_branch_names(title: str, slug: str) -> None:
    assert re.fullmatch(rf"agent/{re.escape(slug)}-[0-9a-f]{{6}}", branch_name(title))


async def test_link_symlinks_existing_sources_and_reports_the_rest(
    manager: WorktreeManager, tmp_path: Path
) -> None:
    config = WorktreeConfig(link=[".env", "config/app.local.json", "missing.env", "README.md"])
    repo = make_repo(tmp_path, config)
    (repo.path / ".env").write_text("SECRET=1", encoding="utf-8")
    (repo.path / "config").mkdir()
    (repo.path / "config" / "app.local.json").write_text("{}", encoding="utf-8")
    worktree = await manager.create(repo, "session-1", "t")

    result = manager.link(repo, worktree.path)

    assert result.linked == [".env", "config/app.local.json"]
    assert result.missing == ["missing.env"]
    assert result.existing == ["README.md"]
    assert (worktree.path / ".env").readlink() == repo.path / ".env"
    assert (worktree.path / "config" / "app.local.json").read_text(encoding="utf-8") == "{}"
    assert not (worktree.path / "README.md").is_symlink()


async def test_setup_runs_commands_in_order_in_the_worktree_and_logs_output(
    manager: WorktreeManager, paths: AppPaths, tmp_path: Path
) -> None:
    repo = make_repo(
        tmp_path, WorktreeConfig(setup=["pwd -P > where.txt", "echo out; echo err >&2"])
    )
    worktree = await manager.create(repo, "session-1", "t")

    result = await manager.run_setup(repo, worktree.path, "session-1")

    assert result.ok is True
    assert result.log_path == paths.logs_dir / "setup-session-1.log"
    where = (worktree.path / "where.txt").read_text(encoding="utf-8").strip()
    assert where == git(worktree.path, "rev-parse", "--show-toplevel").strip()
    log = result.log_path.read_text(encoding="utf-8")
    assert (
        log
        == "$ pwd -P > where.txt\nexit code 0\n$ echo out; echo err >&2\nout\nerr\nexit code 0\n"
    )


async def test_setup_stops_at_the_first_failure(manager: WorktreeManager, tmp_path: Path) -> None:
    repo = make_repo(tmp_path, WorktreeConfig(setup=["exit 3", "touch never"]))
    worktree = await manager.create(repo, "session-1", "t")

    result = await manager.run_setup(repo, worktree.path, "session-1")

    assert result.ok is False
    assert result.command == "exit 3"
    assert result.exit_code == 3
    assert result.timed_out is False
    assert not (worktree.path / "never").exists()


async def test_setup_times_out_and_kills_the_command(
    manager: WorktreeManager, tmp_path: Path
) -> None:
    config = WorktreeConfig(setup=["sleep 30 & wait", "touch never"], setup_timeout_seconds=1)
    repo = make_repo(tmp_path, config)
    worktree = await manager.create(repo, "session-1", "t")

    result = await manager.run_setup(repo, worktree.path, "session-1")

    assert result.ok is False
    assert result.timed_out is True
    assert result.exit_code is None
    assert result.command == "sleep 30 & wait"
    assert result.log_path.read_text(encoding="utf-8").endswith("timed out after 1s\n")
    assert not (worktree.path / "never").exists()


async def test_remove_deletes_the_worktree_and_optionally_the_branch(
    manager: WorktreeManager, tmp_path: Path
) -> None:
    repo = make_repo(tmp_path)
    kept = await manager.create(repo, "aaaaaaaa", "keep")
    dropped = await manager.create(repo, "bbbbbbbb", "drop")
    (kept.path / "untracked.txt").write_text("x", encoding="utf-8")

    await manager.remove(repo, kept, delete_branch=False)
    await manager.remove(repo, dropped, delete_branch=True)

    assert not kept.path.exists()
    assert not dropped.path.exists()
    assert kept.branch in branches(repo)
    assert dropped.branch not in branches(repo)


async def test_remove_prunes_a_worktree_whose_directory_is_gone(
    manager: WorktreeManager, tmp_path: Path
) -> None:
    repo = make_repo(tmp_path)
    worktree = await manager.create(repo, "session-1", "gone")
    shutil.rmtree(worktree.path)

    await manager.remove(repo, Worktree(worktree.path, worktree.branch, ""), delete_branch=True)

    assert "gone" not in git(repo.path, "worktree", "list")
    assert worktree.branch not in branches(repo)


async def test_removing_twice_is_harmless(manager: WorktreeManager, tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    worktree = await manager.create(repo, "session-2", "twice")
    await manager.remove(repo, worktree, delete_branch=True)

    await manager.remove(repo, worktree, delete_branch=True)

    assert worktree.branch not in branches(repo)


async def test_dirty_files(manager: WorktreeManager, tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    assert await manager.dirty_files(repo) == []
    commit_file(repo.path, "old name.txt")
    git(repo.path, "mv", "old name.txt", "new name.txt")
    (repo.path / "README.md").write_text("changed", encoding="utf-8")
    (repo.path / "untracked.txt").write_text("x", encoding="utf-8")

    assert await manager.dirty_files(repo) == ["README.md", "new name.txt", "untracked.txt"]


async def test_head_is_the_current_commit_or_none(manager: WorktreeManager, tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    empty = tmp_path / "empty"
    empty.mkdir()
    git(empty, "init", "-q")

    assert await manager.head(repo) == git(repo.path, "rev-parse", "HEAD").strip()
    assert await manager.head(RepoConfig(name="empty", path=empty)) is None


def process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


async def test_cancelling_setup_kills_the_running_command(tmp_path: Path) -> None:
    pid_file = tmp_path / "pid"
    running = asyncio.ensure_future(
        run_commands([f"sleep 30 & echo $! > {pid_file}; wait"], tmp_path, tmp_path / "log", 60)
    )
    await until(lambda: pid_file.exists() and pid_file.read_text(encoding="utf-8").strip() != "")
    pid = int(pid_file.read_text(encoding="utf-8"))

    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running

    await until(lambda: not process_exists(pid))


async def test_remove_deletes_files_written_after_git_removed_the_worktree(
    manager: WorktreeManager, tmp_path: Path
) -> None:
    repo = make_repo(tmp_path)
    worktree = await manager.create(repo, "session-1", "late hook")
    git(repo.path, "worktree", "remove", "--force", str(worktree.path))
    # An agent exit hook recreating the directory after removal.
    (worktree.path / ".remember").mkdir(parents=True)
    (worktree.path / ".remember" / "notes.md").write_text("x", encoding="utf-8")

    await manager.remove(repo, worktree, delete_branch=True)

    assert not worktree.path.exists()
    assert worktree.branch not in branches(repo)


@pytest.mark.parametrize(
    "where",
    [
        "elsewhere",
        "data/worktrees/../escaped",
        "repo/.claude/worktrees/agent-claude",
        "repo/.claude/worktrees/harness-x/../agent-escaped",
        "repo/.claude/harness-misplaced",
        "repo/src",
    ],
)
async def test_remove_never_deletes_directories_outside_harness_worktrees(
    manager: WorktreeManager, tmp_path: Path, where: str
) -> None:
    repo = make_repo(tmp_path)
    outside = tmp_path / where
    outside.mkdir(parents=True)
    (outside / "keep.txt").write_text("x", encoding="utf-8")

    await manager.remove(repo, Worktree(outside, "agent/none", ""), delete_branch=False)

    assert (outside / "keep.txt").exists()


async def test_remove_still_deletes_a_worktree_in_the_data_dir(
    manager: WorktreeManager, paths: AppPaths, tmp_path: Path
) -> None:
    repo = make_repo(tmp_path)
    legacy = paths.worktrees_dir / "repo" / "0123abcd"
    git(repo.path, "worktree", "add", "-q", "-b", "agent/legacy", str(legacy))

    await manager.remove(repo, Worktree(legacy, "agent/legacy", ""), delete_branch=True)

    assert not legacy.exists()
    assert "agent/legacy" not in branches(repo)


async def test_remove_without_the_repo_folder_only_deletes_the_leftover_directory(
    manager: WorktreeManager, paths: AppPaths, tmp_path: Path
) -> None:
    repo = make_repo(tmp_path)
    leftover = paths.worktrees_dir / "repo" / "0123abcd"
    git(repo.path, "worktree", "add", "-q", "-b", "agent/orphan", str(leftover))
    worktree = await manager.create(repo, "session-3", "orphan")
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    shutil.rmtree(repo.path)

    await manager.remove(repo, Worktree(leftover, "agent/orphan", ""), delete_branch=True)
    await manager.remove(repo, worktree, delete_branch=True)
    await manager.remove(repo, Worktree(outside, "agent/none", ""), delete_branch=True)

    assert not leftover.exists()
    assert not worktree.path.exists()
    assert outside.is_dir()


async def test_has_work_counts_changes_and_commits_since_the_base(
    manager: WorktreeManager, tmp_path: Path
) -> None:
    repo = make_repo(tmp_path)
    worktree = await manager.create(repo, "s1", "Fix")

    clean = await manager.has_work(worktree)
    (worktree.path / "new.txt").write_text("x\n", encoding="utf-8")
    untracked = await manager.has_work(worktree)
    git(worktree.path, "add", "new.txt")
    git(worktree.path, "commit", "-q", "-m", "add")
    committed = await manager.has_work(worktree)
    gone = await manager.has_work(Worktree(tmp_path / "missing", "b", worktree.base_ref))
    plain = tmp_path / "plain"
    plain.mkdir()
    unknown = await manager.has_work(Worktree(plain, "b", worktree.base_ref))

    assert (clean, untracked, committed) == (False, True, True)
    assert gone is False
    # git cannot tell outside a repository: kept, to be safe.
    assert unknown is True
