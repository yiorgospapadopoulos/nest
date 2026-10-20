"""B97: changes on disk to the engines' setup are announced as `configuration.changed`."""

import asyncio
import json
import os
from collections.abc import AsyncIterator, Sequence
from pathlib import Path

import pytest

from nestd.configuration.engines import CodexLocations, codex_versions
from nestd.configuration.locations import Locations
from nestd.configuration.service import prepare_engine
from nestd.configuration.watcher import ConfigurationWatcher, snapshot
from nestd.events import types
from nestd.events.bus import EventBus
from nestd.events.models import Event
from nestd.gitops.runner import CommandError
from nestd.storage.db import Database
from tests.configuration_support import locations, skill
from tests.fakes import FakeClock


@pytest.fixture
def where(tmp_path: Path) -> Locations:
    return locations(tmp_path)


@pytest.fixture
async def heard(db: Database, clock: FakeClock) -> AsyncIterator[tuple[EventBus, list[Event]]]:
    bus = EventBus(db, clock)
    events: list[Event] = []

    async def listen() -> None:
        async for event in bus.subscribe():
            events.append(event)

    task = asyncio.create_task(listen())
    await asyncio.sleep(0)
    yield bus, events
    task.cancel()


def touch(path: Path, text: str, seconds: int) -> None:
    """Write and give it a later modification time than any write before."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    stamp = 1_800_000_000 + seconds
    os.utime(path, (stamp, stamp))


async def payloads(events: list[Event]) -> list[dict[str, object]]:
    await asyncio.sleep(0.01)
    return [dict(e.payload) for e in events if e.type == types.CONFIGURATION_CHANGED]


async def test_changes_are_announced_once_a_look(
    heard: tuple[EventBus, list[Event]], where: Locations, tmp_path: Path
) -> None:
    bus, events = heard
    repo = tmp_path / "repo"
    repo.mkdir()
    watcher = ConfigurationWatcher(bus, where, lambda: {"repo": repo})

    await watcher.tick()
    assert await payloads(events) == []

    touch(where.claude_md, "one", 1)
    skill(where.shared_skills, "release")
    await watcher.tick()
    assert await payloads(events) == [{"scope": "user", "repo": None}]

    await watcher.tick()
    touch(repo / ".mcp.json", "{}", 2)
    await watcher.tick()
    assert (await payloads(events))[1:] == [{"scope": "repo", "repo": "repo"}]


async def test_only_the_mcp_servers_of_claude_json_count(
    heard: tuple[EventBus, list[Event]], where: Locations
) -> None:
    bus, events = heard
    touch(where.claude_json, json.dumps({"numStartups": 1}), 1)
    watcher = ConfigurationWatcher(bus, where, dict)
    await watcher.tick()

    touch(where.claude_json, json.dumps({"numStartups": 2}), 2)
    await watcher.tick()
    assert await payloads(events) == []

    touch(where.claude_json, json.dumps({"numStartups": 2, "mcpServers": {"x": {}}}), 3)
    await watcher.tick()
    touch(where.claude_json, "{broken", 4)
    await watcher.tick()
    assert len(await payloads(events)) == 2


async def test_a_new_repo_is_only_remembered(
    heard: tuple[EventBus, list[Event]], tmp_path: Path
) -> None:
    bus, events = heard
    repos: dict[str, Path] = {}
    watcher = ConfigurationWatcher(bus, None, lambda: repos)
    await watcher.tick()
    repos["repo"] = tmp_path
    await watcher.tick()

    assert await payloads(events) == []


async def test_the_watcher_polls_until_stopped(
    heard: tuple[EventBus, list[Event]], where: Locations
) -> None:
    bus, events = heard
    calls: list[int] = []
    first = asyncio.Event()
    fourth = asyncio.Event()

    def repos() -> dict[str, Path]:
        calls.append(1)
        first.set()
        if len(calls) == 2:
            raise OSError("gone")
        if len(calls) == 4:
            fourth.set()
        return {}

    watcher = ConfigurationWatcher(bus, where, repos, interval=0.001)
    await watcher.start()
    await watcher.start()
    async with asyncio.timeout(5):
        await first.wait()
        touch(where.claude_md, "x", 5)
        await fourth.wait()
    await watcher.stop()
    await watcher.stop()

    assert await payloads(events) == [{"scope": "user", "repo": None}]


def test_a_snapshot_sees_folders_files_and_links(where: Locations, tmp_path: Path) -> None:
    skill(where.shared_skills, "release")
    where.codex_skills.mkdir()
    where.skills_link.symlink_to(where.shared_skills)

    found = snapshot([where.shared_skills, where.codex_skills, tmp_path / "missing"])

    assert str(where.shared_skills / "release" / "SKILL.md") in found
    assert str(where.skills_link) in found
    assert not any(key.startswith(str(where.skills_link / "release")) for key in found)


def test_engine_files_are_prepared_after_sign_in(where: Locations) -> None:
    prepare_engine(where, "claude")
    prepare_engine(where, "codex")

    assert where.shared_skills.is_dir()
    assert where.shared_instructions.read_text(encoding="utf-8") == ""
    where.shared_instructions.write_text("# Mine\n", encoding="utf-8")
    prepare_engine(where, "codex")
    assert where.shared_instructions.read_text(encoding="utf-8") == "# Mine\n"


async def test_codex_locations(tmp_path: Path) -> None:
    bundled = tmp_path / "bundled" / "codex"
    bundled.parent.mkdir()
    bundled.write_text("#!/bin/sh\n", encoding="utf-8")
    bundled.chmod(0o755)

    found = CodexLocations.default(tmp_path, {"PATH": str(bundled.parent)}, bundled)

    assert found.bundled_version is not None
    assert found.search_path == str(bundled.parent)
    assert found.candidates[-1] == tmp_path / ".local" / "bin" / "codex"
    mine = CodexLocations(str(bundled.parent), (), bundled, "1.0")
    assert mine.standalone() is None

    async def fails(argv: Sequence[str], cwd: Path) -> str:
        raise CommandError(argv, 1, "no")

    other = CodexLocations(str(bundled.parent), (), None, "1.0")
    versions = await codex_versions(other, fails, tmp_path)
    assert versions.standalone is not None
    assert versions.standalone.version is None


async def test_codex_locations_without_the_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import importlib.metadata

    def missing(_name: str) -> str:
        raise importlib.metadata.PackageNotFoundError

    monkeypatch.setattr(importlib.metadata, "version", missing)

    assert CodexLocations.default(tmp_path, {}, None).bundled_version is None
