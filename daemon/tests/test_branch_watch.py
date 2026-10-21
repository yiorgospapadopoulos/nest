"""The poller that announces a repo's worktrees and checked-out branch changing (B96), by
Nest, Claude Code or a terminal alike.
"""

import asyncio
import logging
import shutil
from collections.abc import AsyncIterator, Mapping
from datetime import timedelta
from pathlib import Path

import pytest
from pydantic import JsonValue

from nestd.events import types
from nestd.events.bus import EventBus
from nestd.paths import AppPaths
from nestd.repos.branch_watch import BranchWatch
from nestd.repos.service import RepoService
from nestd.storage.db import Database
from tests.async_support import until
from tests.fakes import FakeClock
from tests.git_support import git, init_repo


class Setup:
    def __init__(self, tmp_path: Path, db: Database, clock: FakeClock) -> None:
        self.tmp_path = tmp_path
        self.paths = AppPaths(config_dir=tmp_path / "config", data_dir=tmp_path / "data")
        self.paths.ensure()
        self.repos = RepoService(self.paths)
        self.bus = EventBus(db, clock)
        self.published: list[tuple[str, Mapping[str, JsonValue]]] = []
        self.watch = self.build(timedelta(hours=1))

    def build(self, interval: timedelta) -> BranchWatch:
        return BranchWatch(repos=self.repos, bus=self.bus, interval=interval)

    def names(self) -> list[JsonValue]:
        return [payload["name"] for _, payload in self.published]


@pytest.fixture
async def setup(
    tmp_path: Path, db: Database, clock: FakeClock, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[Setup]:
    environment = Setup(tmp_path, db, clock)
    for name in ("alpha", "beta"):
        await environment.repos.register(init_repo(tmp_path / name))
    plain = tmp_path / "notes"
    plain.mkdir()
    await environment.repos.register(plain)

    async def record(
        event_type: str, payload: Mapping[str, JsonValue], session_id: str | None = None
    ) -> None:
        assert event_type == types.REPO_BRANCHES_CHANGED
        assert session_id is None
        environment.published.append((event_type, payload))

    monkeypatch.setattr(environment.bus, "publish_ephemeral", record)
    yield environment
    await environment.watch.stop()


async def test_the_first_scan_only_records_and_an_unchanged_repo_is_quiet(setup: Setup) -> None:
    await setup.watch.scan()
    await setup.watch.scan()

    assert setup.published == []


async def test_worktrees_added_or_removed_and_a_branch_switch_are_announced(
    setup: Setup,
) -> None:
    alpha = setup.tmp_path / "alpha"
    worktree = alpha / ".claude" / "worktrees" / "cozy"
    await setup.watch.scan()

    git(alpha, "worktree", "add", "-q", "-b", "cozy", str(worktree))
    await setup.watch.scan()
    added = setup.names()
    git(alpha, "worktree", "remove", str(worktree))
    git(setup.tmp_path / "beta", "checkout", "-q", "-b", "wip")
    await setup.watch.scan()

    assert added == ["alpha"]
    assert setup.names() == ["alpha", "alpha", "beta"]


async def test_a_repo_registered_later_is_recorded_first(setup: Setup) -> None:
    await setup.watch.scan()
    gamma = init_repo(setup.tmp_path / "gamma")
    await setup.repos.register(gamma)

    await setup.watch.scan()
    git(gamma, "checkout", "-q", "-b", "wip")
    await setup.watch.scan()

    assert setup.names() == ["gamma"]


async def test_a_failing_repo_does_not_stop_the_others(setup: Setup) -> None:
    # Gone before the first scan, and alpha after it.
    await setup.repos.register(init_repo(setup.tmp_path / "gamma"))
    shutil.rmtree(setup.tmp_path / "gamma")
    await setup.watch.scan()
    shutil.rmtree(setup.tmp_path / "alpha")
    git(setup.tmp_path / "beta", "checkout", "-q", "-b", "wip")

    await setup.watch.scan()
    # Readable at last: recorded first, like a new project.
    init_repo(setup.tmp_path / "gamma")
    await setup.watch.scan()

    assert setup.names() == ["beta"]


async def test_polling_runs_until_stopped(
    setup: Setup, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    watch = setup.build(timedelta(milliseconds=5))
    calls: list[int] = []
    scan = watch.scan

    async def counted() -> None:
        calls.append(1)
        if len(calls) == 2:
            git(setup.tmp_path / "alpha", "checkout", "-q", "-b", "wip")
        if len(calls) == 3:
            raise RuntimeError("config unreadable")
        await scan()

    monkeypatch.setattr(watch, "scan", counted)
    with caplog.at_level(logging.ERROR):
        await watch.start()
        await until(lambda: len(calls) >= 5)
        await watch.stop()
    await watch.stop()
    stopped = len(calls)
    await asyncio.sleep(0.02)

    assert setup.names() == ["alpha"]
    assert "watching the branches of the projects failed" in caplog.text
    assert len(calls) == stopped
