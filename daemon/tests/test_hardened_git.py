"""I-009: the daemon's other git commands in a repository an agent can write run with the
same overrides as publishing and diffs (D050): no hooks, no fsmonitor program, no filter
driver the agent could have added.
"""

import stat
from collections.abc import Sequence
from datetime import timedelta
from pathlib import Path

import pytest

from harness.config.models import RepoConfig
from harness.gitops import runner
from harness.gitops.hardened import nested_filter_overrides
from harness.gitops.runner import GitError, run_command
from harness.gitops.safety import HARDENED
from harness.paths import AppPaths
from harness.repos.service import RepoService
from harness.sessions.files import FileIndex
from harness.sessions.git_audit import snapshot_refs, with_own_changes
from harness.worktrees.manager import WorktreeManager
from tests.fakes import FakeClock
from tests.git_support import commit_file, git, init_repo
from tests.nested_support import add_nested_repo, plant_filter


def marker_script(path: Path, marker: Path, body: str = "") -> Path:
    path.write_text(f'#!/bin/sh\necho ran >> "{marker}"\n{body}', encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


@pytest.fixture
def paths(tmp_path: Path) -> AppPaths:
    result = AppPaths(config_dir=tmp_path / "config", data_dir=tmp_path / "data")
    result.ensure()
    return result


async def test_creating_a_worktree_runs_no_hook_or_agent_filter(
    paths: AppPaths, tmp_path: Path
) -> None:
    repo = init_repo(tmp_path / "repo")
    (repo / ".gitattributes").write_text("*.txt filter=evil\n", encoding="utf-8")
    (repo / "notes.txt").write_text("plain\n", encoding="utf-8")
    git(repo, "add", ".gitattributes", "notes.txt")
    git(repo, "commit", "-q", "-m", "files")
    hook_marker, filter_marker = tmp_path / "hook-ran", tmp_path / "filter-ran"
    marker_script(repo / ".git" / "hooks" / "post-checkout", hook_marker)
    smudge = marker_script(tmp_path / "smudge.sh", filter_marker, "cat\n")
    git(repo, "config", "filter.evil.smudge", str(smudge))
    git(repo, "config", "filter.evil.required", "true")

    worktree = await WorktreeManager(paths).create(
        RepoConfig(name="repo", path=repo), "0123456789", "task"
    )

    assert (worktree.path / "notes.txt").read_text(encoding="utf-8") == "plain\n"
    assert not hook_marker.exists()
    assert not filter_marker.exists()


async def test_listing_dirty_files_runs_no_fsmonitor_program(
    paths: AppPaths, tmp_path: Path
) -> None:
    repo = init_repo(tmp_path / "repo")
    marker = tmp_path / "fsmonitor-ran"
    git(repo, "config", "core.fsmonitor", str(marker_script(tmp_path / "fsm.sh", marker)))
    (repo / "README.md").write_text("changed\n", encoding="utf-8")
    manager = WorktreeManager(paths)

    for _ in range(2):  # git asks the monitor once the index records it
        assert await manager.dirty_files(RepoConfig(name="repo", path=repo)) == ["README.md"]

    assert not marker.exists()


async def test_listing_dirty_files_runs_no_filter_of_a_nested_repository(
    paths: AppPaths, tmp_path: Path
) -> None:
    """SEC-08: git would run `status` inside it, with its own config."""
    repo = init_repo(tmp_path / "repo")
    nested = add_nested_repo(repo)
    marker = tmp_path / "filter-ran"
    plant_filter(nested, marker)
    (repo / "README.md").write_text("changed\n", encoding="utf-8")

    dirty = await WorktreeManager(paths).dirty_files(RepoConfig(name="repo", path=repo))
    assert not marker.exists()
    commit_file(nested, "more.txt", "more\n")
    moved = await WorktreeManager(paths).dirty_files(RepoConfig(name="repo", path=repo))

    assert dirty == ["README.md"]
    # A new commit in the nested repository is a change of the work.
    assert moved == ["README.md", "lib"]


async def test_every_git_command_on_an_agent_writable_repo_is_hardened(
    paths: AppPaths, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_path = init_repo(tmp_path / "repo")
    (repo_path / ".env").write_text("A=1\n", encoding="utf-8")
    (repo_path / ".gitignore").write_text(".env\n", encoding="utf-8")
    plain = tmp_path / "plain"
    plain.mkdir()
    commands: list[Sequence[str]] = []
    real = runner.run_command

    async def recording(argv: Sequence[str], cwd: Path, time_limit: float = 300.0) -> str:
        commands.append(argv)
        return await real(argv, cwd, time_limit)

    monkeypatch.setattr(runner, "run_command", recording)
    repos = RepoService(paths)
    repo = await repos.register(repo_path)
    plain_repo = await repos.register(plain)
    commands.clear()

    manager = WorktreeManager(paths)
    worktree = await manager.create(repo, "0123456789", "task")
    await manager.head(repo)
    await manager.dirty_files(repo)
    baseline = await snapshot_refs(worktree.path)
    await with_own_changes(worktree.path, baseline, "origin")
    assert await snapshot_refs(plain) == {}
    await FileIndex(FakeClock(), ttl=timedelta(0)).search(worktree.path, "read")
    assert await repos.suggest_links(repo.name) == [".env"]
    (plain / ".git").mkdir()  # a stat says maybe; git says no
    await repos.current(plain_repo.name)
    await manager.remove(repo, worktree, delete_branch=True)

    git_commands = [argv for argv in commands if argv[0] == "git"]
    assert len(git_commands) > 10
    assert [argv for argv in git_commands if tuple(argv[1 : 1 + len(HARDENED)]) != HARDENED] == []


async def test_a_filter_driver_that_cannot_be_switched_off_stops_the_checkout(
    paths: AppPaths, tmp_path: Path
) -> None:
    repo = init_repo(tmp_path / "repo")
    git(repo, "config", "filter.a=b.smudge", "sh -c evil")

    with pytest.raises(GitError, match="cannot be switched off"):
        await WorktreeManager(paths).create(RepoConfig(name="repo", path=repo), "0123456789", "x")


async def test_nested_filters_are_found_once_and_only_in_populated_repositories(
    tmp_path: Path,
) -> None:
    """SEC-08: a gitlink path can be missing, or a symlink back to a folder already read."""
    repo = init_repo(tmp_path / "repo")
    nested = add_nested_repo(repo)
    git(nested, "config", "filter.inner.clean", "evil")
    sha = git(nested, "rev-parse", "HEAD").strip()
    for name in ("missing", "loop"):
        git(repo, "update-index", "--add", "--cacheinfo", f"160000,{sha},{name}")
    (repo / "loop").symlink_to(".")
    looked_in: list[Path] = []

    async def recording(argv: Sequence[str], cwd: Path) -> str:
        looked_in.append(cwd)
        return await run_command(argv, cwd)

    overrides = await nested_filter_overrides(repo, recording)

    # The index of each repository and the config of the nested one, each read once.
    assert looked_in == [repo, nested, nested]
    assert overrides == [
        *("-c", "filter.inner.clean="),
        *("-c", "filter.inner.smudge="),
        *("-c", "filter.inner.process="),
        *("-c", "filter.inner.required=false"),
    ]
