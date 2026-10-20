"""Live configuration (B97): the engines' setup files are polled every 2 s, and a change on
disk, whoever made it, is announced as `configuration.changed` (no new dependency).

Each scope (the user's setup, or one repo's) is announced at most once a poll. Of
`.claude.json`, which Claude Code rewrites all the time, only the MCP servers count.
"""

import asyncio
import json
import logging
import os
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path

from pydantic import JsonValue

from nestd.configuration.files import read_text, version_of
from nestd.configuration.locations import (
    CLAUDE_FILES,
    CLAUDE_FOLDERS,
    CODEX_FOLDERS,
    REPO_FILES,
    REPO_SKILLS,
    Locations,
)
from nestd.configuration.mcp import SERVERS_KEY
from nestd.events import types
from nestd.events.bus import EventBus

logger = logging.getLogger(__name__)

INTERVAL_SECONDS = 2.0
USER = "user"
type Snapshot = dict[str, str]


def user_paths(where: Locations) -> list[Path]:
    claude = where.claude_dir
    codex = where.codex_home
    return [
        *(claude / name for name in (*CLAUDE_FILES, *CLAUDE_FOLDERS)),
        codex / "AGENTS.md",
        codex / "config.toml",
        *(codex / name for name in CODEX_FOLDERS),
    ]


def repo_paths(repo: Path) -> list[Path]:
    return [*(repo / name for name in REPO_FILES), repo / REPO_SKILLS]


def snapshot(paths: list[Path], servers_file: Path | None = None) -> Snapshot:
    """Every file, folder and link under `paths` with its modification time and size
    (links not followed), plus a fingerprint of `servers_file`'s MCP servers.
    """
    found: Snapshot = {}
    for path in paths:
        _note(path, found)
        for root, folders, files in os.walk(path):
            for name in (*folders, *files):
                _note(Path(root) / name, found)
    if servers_file is not None:
        found[str(servers_file)] = _servers(servers_file)
    return found


def _note(path: Path, found: Snapshot) -> None:
    with suppress(FileNotFoundError):
        stat = path.lstat()
        found[str(path)] = f"{stat.st_mtime_ns} {stat.st_size} {stat.st_mode}"


def _servers(path: Path) -> str:
    try:
        data: JsonValue = json.loads(read_text(path) or "{}")
    except ValueError:
        return "invalid"
    servers = data.get(SERVERS_KEY) if isinstance(data, dict) else None
    return version_of(json.dumps(servers, sort_keys=True).encode())


class ConfigurationWatcher:
    def __init__(
        self,
        bus: EventBus,
        where: Locations | None,
        repos: Callable[[], dict[str, Path]],
        interval: float = INTERVAL_SECONDS,
    ) -> None:
        """`repos` gives each registered repo's folder by name, read at each poll."""
        self._bus = bus
        self._where = where
        self._repos = repos
        self._interval = interval
        self._seen: dict[str, Snapshot] = {}
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    async def tick(self) -> None:
        """Look once; the first look at a scope only remembers it."""
        now = await asyncio.to_thread(self._look)
        for scope, files in now.items():
            before = self._seen.get(scope)
            if before is not None and before != files:
                repo = None if scope == USER else scope.removeprefix("repo:")
                payload: dict[str, JsonValue] = {"scope": "user" if repo is None else "repo"}
                payload["repo"] = repo
                await self._bus.publish_ephemeral(types.CONFIGURATION_CHANGED, payload)
        self._seen = now

    def _look(self) -> dict[str, Snapshot]:
        scopes: dict[str, Snapshot] = {}
        if self._where is not None:
            scopes[USER] = snapshot(user_paths(self._where), self._where.claude_json)
        for name, folder in self._repos().items():
            scopes[f"repo:{name}"] = snapshot(repo_paths(folder))
        return scopes

    async def _loop(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception:
                logger.exception("could not look for configuration changes")
            await asyncio.sleep(self._interval)
