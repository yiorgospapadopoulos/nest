"""The engines the updater follows, and how their versions read to people."""

import importlib
from collections.abc import Mapping
from dataclasses import dataclass
from importlib import metadata

from pydantic import BaseModel

from nestd.providers.acp_engines import ACP_ENGINES, AcpEngine
from nestd.updates.pypi import CLAUDE_PACKAGE, CODEX_PACKAGE


@dataclass(frozen=True)
class FollowedEngine:
    id: str
    name: str
    package: str
    on_npm: bool


@dataclass(frozen=True)
class Versions:
    # Engine id to the package version.
    packages: Mapping[str, str]
    # Engine id to the version people see; Claude's is Claude Code's, not the SDK's.
    shown: Mapping[str, str]


class EngineUpdate(BaseModel):
    id: str
    name: str
    current: str
    new: str


def npm_engines() -> tuple[AcpEngine, ...]:
    """The ACP engines Nest fetches, at the versions of this environment."""
    return tuple(engine for engine in ACP_ENGINES if engine.delivery == "bundled")


def followed_engines() -> tuple[FollowedEngine, ...]:
    return (
        FollowedEngine("claude", "Claude Code", CLAUDE_PACKAGE, on_npm=False),
        FollowedEngine("codex", "Codex", CODEX_PACKAGE, on_npm=False),
        *(
            FollowedEngine(engine.id, engine.name, engine.package or "", on_npm=True)
            for engine in npm_engines()
        ),
    )


def running_versions() -> Versions:
    """What this process runs, read without starting anything."""
    cli_version: object = importlib.import_module("claude_agent_sdk._cli_version").__cli_version__
    codex = metadata.version(CODEX_PACKAGE)
    fetched = {engine.id: engine.version or "" for engine in npm_engines()}
    return Versions(
        packages={"claude": metadata.version(CLAUDE_PACKAGE), "codex": codex, **fetched},
        shown={"claude": str(cli_version), "codex": codex, **fetched},
    )


def changes(
    now: Versions, packages: Mapping[str, str], shown: Mapping[str, str]
) -> list[EngineUpdate]:
    """What moving to `packages` changes. A package that moves without what people see
    moving (a new SDK with the same Claude Code) shows its package versions.
    """
    updates: list[EngineUpdate] = []
    for engine in followed_engines():
        have, want = now.packages.get(engine.id, ""), packages.get(engine.id)
        if want is None or want == have:
            continue
        current, new = now.shown.get(engine.id, have), shown.get(engine.id, want)
        if current == new:
            current, new = have, want
        updates.append(EngineUpdate(id=engine.id, name=engine.name, current=current, new=new))
    return updates


def summary(updates: list[EngineUpdate]) -> str:
    return ", ".join(f"{update.name} {update.new}" for update in updates)
