"""Codex's skills, MCP servers, plugins, marketplaces and hooks through its app-server
(B97, contract rule 7): a short-lived one each time, on the stable API only. Codex's
config.toml is written only with `config/batchWrite` and the version Codex just read, so
its comments and formatting stay and a change made meanwhile is not overwritten.
"""

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

from pydantic import BaseModel, JsonValue

from nestd.configuration.errors import ChangedOnDiskError, CodexSetupError
from nestd.errors import NestError
from nestd.providers.codex_engine import FETCH_TIMEOUT, CodexFetchError, ask_codex
from nestd.providers.codex_items import items, obj, text
from nestd.providers.codex_process import CodexLaunch, TransportFactory
from nestd.providers.codex_rpc import CodexRpc, CodexRpcError, JsonObject

MCP_KEY = "mcp_servers"
# The keys of a server table Nest writes; a table's other keys are Codex's own and stay.
MANAGED_KEYS = frozenset({"command", "args", "env", "url", "bearer_token_env_var", "http_headers"})
# How Codex names a write against a config.toml that changed since it was read.
VERSION_CONFLICT = "configVersionConflict"
CONFLICT = "Codex's config.toml changed meanwhile; try again"


class _RefusedError(Exception):
    """Codex answered a request with an error; its message names the request's problem."""


@dataclass(frozen=True)
class CodexSkill:
    name: str
    description: str | None
    # SKILL.md as Codex found it, maybe through a link.
    path: Path
    enabled: bool
    plugin_id: str | None
    # "user", "repo", "system" or "admin".
    scope: str


@dataclass(frozen=True)
class CodexSkills:
    skills: list[CodexSkill] = field(default_factory=list[CodexSkill])
    # Why Codex could not load a SKILL.md, by its path.
    errors: dict[Path, str] = field(default_factory=dict[Path, str])


@dataclass(frozen=True)
class CodexUserConfig:
    """The user's own config.toml layer: its MCP server tables and its version."""

    servers: JsonObject = field(default_factory=dict[str, JsonValue])
    version: str | None = None


class CodexPlugin(BaseModel):
    id: str
    name: str
    marketplace: str
    description: str | None
    version: str | None
    installed: bool
    enabled: bool


class CodexMarketplace(BaseModel):
    name: str
    path: str | None


@dataclass(frozen=True)
class CodexCatalog:
    plugins: list[CodexPlugin]
    marketplaces: list[CodexMarketplace]
    # Where each plugin's marketplace is, for installing it.
    marketplace_paths: dict[str, str | None]


class CodexSetup:
    def __init__(
        self,
        factory: TransportFactory,
        launch: Callable[[], CodexLaunch],
        time_limit: timedelta = FETCH_TIMEOUT,
    ) -> None:
        self._factory = factory
        self._launch = launch
        self._time_limit = time_limit

    async def ask[T](self, ask: Callable[[CodexRpc], Awaitable[T]]) -> T:
        """`ask` on a short-lived app-server; 502 naming Codex's refusal or the failure.
        Nest's own errors raised in `ask` pass through as they are.
        """

        async def asking(rpc: CodexRpc) -> T:
            try:
                return await ask(rpc)
            except CodexRpcError as error:
                if VERSION_CONFLICT in f"{error.message} {json.dumps(error.data)}":
                    raise ChangedOnDiskError(CONFLICT, None) from error
                raise _RefusedError(error.message) from error

        try:
            return await ask_codex(self._factory, self._launch(), asking, self._time_limit)
        except CodexFetchError as error:
            cause = error.__cause__
            if isinstance(cause, NestError):
                raise cause from None
            if isinstance(cause, _RefusedError):
                msg = f"Codex refused: {cause}"
                raise CodexSetupError(msg) from error
            msg = f"Codex could not be asked ({error})"
            raise CodexSetupError(msg) from error


async def list_skills(rpc: CodexRpc) -> CodexSkills:
    answer = await rpc.request("skills/list", {"cwds": [], "forceReload": True})
    found = CodexSkills()
    for entry in items(answer.get("data")):
        listing = obj(entry)
        for raw in items(listing.get("skills")):
            skill = obj(raw)
            found.skills.append(
                CodexSkill(
                    name=text(skill.get("name")),
                    description=text(skill.get("description")) or None,
                    path=Path(text(skill.get("path"))),
                    enabled=skill.get("enabled") is not False,
                    plugin_id=text(skill.get("pluginId")) or None,
                    scope=text(skill.get("scope")),
                )
            )
        for raw in items(listing.get("errors")):
            error = obj(raw)
            found.errors[Path(text(error.get("path")))] = text(error.get("message"))
    return found


async def set_skill_enabled(rpc: CodexRpc, path: Path, enabled: bool) -> None:
    await rpc.request("skills/config/write", {"path": str(path), "enabled": enabled})


async def read_user_config(rpc: CodexRpc) -> CodexUserConfig:
    answer = await rpc.request("config/read", {"includeLayers": True})
    for raw in items(answer.get("layers")):
        layer = obj(raw)
        if obj(layer.get("name")).get("type") == "user":
            return CodexUserConfig(
                servers=obj(obj(layer.get("config")).get(MCP_KEY)),
                version=text(layer.get("version")) or None,
            )
    return CodexUserConfig()


async def write_servers(rpc: CodexRpc, changes: dict[str, JsonObject | None]) -> None:
    """Replace or (with None) remove each named server, against the version just read.
    A replaced server keeps the keys of its table Nest does not manage (timeouts, enabled
    tools and the like).
    """
    current = await read_user_config(rpc)
    edits: list[JsonValue] = [
        {
            "keyPath": f"{MCP_KEY}.{name}",
            "value": None if table is None else _merged(current.servers.get(name), table),
            "mergeStrategy": "replace",
        }
        for name, table in changes.items()
    ]
    await rpc.request(
        "config/batchWrite",
        {"edits": edits, "expectedVersion": current.version, "reloadUserConfig": True},
    )


async def read_catalog(rpc: CodexRpc) -> CodexCatalog:
    """Every plugin of every marketplace Codex knows, installed ones included."""
    answer = await rpc.request("plugin/list", {})
    plugins: list[CodexPlugin] = []
    marketplaces: list[CodexMarketplace] = []
    paths: dict[str, str | None] = {}
    for raw in items(answer.get("marketplaces")):
        marketplace = obj(raw)
        name = text(marketplace.get("name"))
        path = text(marketplace.get("path")) or None
        marketplaces.append(CodexMarketplace(name=name, path=path))
        for entry in items(marketplace.get("plugins")):
            plugin = _plugin(obj(entry), name)
            plugins.append(plugin)
            paths[plugin.id] = path
    return CodexCatalog(plugins, marketplaces, paths)


async def installed_count(rpc: CodexRpc) -> int:
    answer = await rpc.request("plugin/installed", {})
    return sum(
        1
        for marketplace in items(answer.get("marketplaces"))
        for plugin in items(obj(marketplace).get("plugins"))
        if obj(plugin).get("installed") is not False
    )


async def user_hooks(rpc: CodexRpc) -> int:
    """The hooks the user set up (not a plugin's or a managed one)."""
    answer = await rpc.request("hooks/list", {"cwds": []})
    return sum(
        1
        for entry in items(answer.get("data"))
        for hook in items(obj(entry).get("hooks"))
        if obj(hook).get("source") == "user"
    )


def _merged(old: JsonValue, table: JsonObject) -> JsonObject:
    kept = {key: value for key, value in obj(old).items() if key not in MANAGED_KEYS}
    return {**kept, **table}


def _plugin(plugin: JsonObject, marketplace: str) -> CodexPlugin:
    interface = obj(plugin.get("interface"))
    return CodexPlugin(
        id=text(plugin.get("id")),
        name=text(plugin.get("name")),
        marketplace=marketplace,
        description=text(interface.get("shortDescription")) or None,
        version=text(plugin.get("version")) or text(plugin.get("localVersion")) or None,
        installed=plugin.get("installed") is True,
        enabled=plugin.get("enabled") is True,
    )
