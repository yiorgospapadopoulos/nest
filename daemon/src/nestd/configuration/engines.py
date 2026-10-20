"""Each engine's own part of the page (B97): who it runs as, its versions and what it
has besides the shared items, counted from its own files.
"""

import importlib.metadata
import json
import os
import shutil
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Self

from pydantic import JsonValue

from nestd.configuration.files import read_text
from nestd.configuration.locations import Locations
from nestd.configuration.models import EngineItem, Standalone
from nestd.gitops.runner import CommandError, CommandRunner

CODEX_PACKAGE = "openai-codex-cli-bin"


@dataclass(frozen=True)
class EngineAccount:
    # None when the engine could not be asked.
    signed_in: bool | None
    label: str | None = None


def account_label(*parts: str | None) -> str | None:
    shown = [part for part in parts if part]
    return " · ".join(shown) or None


@dataclass(frozen=True)
class Versions:
    bundled: str | None
    standalone: Standalone | None


@dataclass(frozen=True)
class EngineProbe:
    """How the page learns an engine's account and versions."""

    account: Callable[[], Awaitable[EngineAccount]]
    versions: Callable[[], Awaitable[Versions]]


@dataclass(frozen=True)
class CodexLocations:
    # The PATH searched for `codex`; "" searches nothing.
    search_path: str
    # Where installers put a standalone Codex, checked after the PATH.
    candidates: tuple[Path, ...]
    # Nest's own copy, never reported as standalone.
    bundled: Path | None
    bundled_version: str | None

    @classmethod
    def default(cls, home: Path, env: Mapping[str, str], bundled: Path | None) -> Self:
        try:
            version: str | None = importlib.metadata.version(CODEX_PACKAGE)
        except importlib.metadata.PackageNotFoundError:
            version = None
        return cls(
            search_path=env.get("PATH", ""),
            candidates=(
                Path("/opt/homebrew/bin/codex"),
                Path("/usr/local/bin/codex"),
                home / ".local" / "bin" / "codex",
            ),
            bundled=bundled,
            bundled_version=version,
        )

    def standalone(self) -> Path | None:
        found = shutil.which("codex", path=self.search_path) if self.search_path else None
        for path in (*([Path(found)] if found else []), *self.candidates):
            if path != self.bundled and path.is_file() and os.access(path, os.X_OK):
                return path
        return None


async def codex_versions(where: CodexLocations, run: CommandRunner, cwd: Path) -> Versions:
    path = where.standalone()
    if path is None:
        return Versions(where.bundled_version, None)
    try:
        output = await run([str(path), "--version"], cwd)
    except (CommandError, OSError):
        version = None
    else:
        words = output.split()
        version = words[-1] if words else None
    return Versions(where.bundled_version, Standalone(path=str(path), version=version))


def claude_items(where: Locations, connectors: int) -> list[EngineItem]:
    settings = _json(where.claude_settings)
    plugins = settings.get("enabledPlugins")
    enabled = sum(1 for on in plugins.values() if on is True) if isinstance(plugins, dict) else 0
    allow, deny, ask = (_rules(settings, kind) for kind in ("allow", "deny", "ask"))
    detail = " · ".join(
        f"{count} {kind}"
        for count, kind in ((allow, "allow"), (deny, "deny"), (ask, "ask"))
        if count
    )
    path = str(where.claude_settings)
    return [
        EngineItem(kind="plugins", count=enabled),
        EngineItem(kind="connectors", count=connectors),
        EngineItem(kind="hooks", count=_claude_hooks(settings), path=path),
        EngineItem(
            kind="subagents",
            count=_count(where.claude_dir / "agents", "*.md"),
            path=str(where.claude_dir / "agents"),
            folder=True,
        ),
        EngineItem(
            kind="commands",
            count=_count(where.claude_dir / "commands", "**/*.md"),
            path=str(where.claude_dir / "commands"),
            folder=True,
        ),
        EngineItem(kind="permissions", count=allow + deny + ask, detail=detail or None, path=path),
        EngineItem(kind="settings", count=None, path=path),
    ]


def codex_items(where: Locations, plugins: int, hooks: int) -> list[EngineItem]:
    rules = where.codex_home / "rules"
    return [
        EngineItem(kind="plugins", count=plugins),
        EngineItem(kind="hooks", count=hooks),
        EngineItem(kind="rules", count=_count(rules, "**/*"), path=str(rules), folder=True),
        EngineItem(kind="settings", count=None, path=str(where.codex_config)),
    ]


def _json(path: Path) -> dict[str, JsonValue]:
    try:
        data: JsonValue = json.loads(read_text(path) or "{}")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _rules(settings: dict[str, JsonValue], kind: str) -> int:
    permissions = settings.get("permissions")
    rules = permissions.get(kind) if isinstance(permissions, dict) else None
    return len(rules) if isinstance(rules, list) else 0


def _claude_hooks(settings: dict[str, JsonValue]) -> int:
    """Each command under each matcher of each event."""
    events = settings.get("hooks")
    if not isinstance(events, dict):
        return 0
    count = 0
    for matchers in events.values():
        for matcher in matchers if isinstance(matchers, list) else []:
            hooks = matcher.get("hooks") if isinstance(matcher, dict) else None
            count += len(hooks) if isinstance(hooks, list) else 0
    return count


def _count(folder: Path, pattern: str) -> int:
    return sum(1 for path in folder.glob(pattern) if path.is_file())
