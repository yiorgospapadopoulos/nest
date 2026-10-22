"""Settings > Configuration (B97): the page, and every change to the engines' files.

The engines' files are the only source of truth (contract rule 1): every answer is read
from them now, and every change is written to them after a backup (rule 2). Changes run
one at a time.
"""

import asyncio
import logging
import tomllib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from functools import partial
from pathlib import Path

from nestd.config.models import ConfigurationSettings
from nestd.configuration import codex as codex_api
from nestd.configuration.backups import Backup, Backups, remove
from nestd.configuration.codex import CodexSetup
from nestd.configuration.engines import EngineProbe
from nestd.configuration.errors import (
    ChangedOnDiskError,
    CodexSetupError,
    ConfigurationUnavailableError,
    PathNotAllowedError,
    UnknownItemError,
)
from nestd.configuration.files import file_version, read_text, write_text
from nestd.configuration.instructions import with_import, without_import
from nestd.configuration.locations import Locations
from nestd.configuration.mcp import McpServer, ServersFile, to_codex
from nestd.configuration.models import (
    ConfigurationPage,
    EngineId,
    FileText,
    FileVersion,
    SharedItem,
)
from nestd.configuration.page import CodexView, Facts, State, build_page, skill_items
from nestd.configuration.skills import (
    CLAUDE_ONLY,
    FoundSkill,
    create_skill,
    find_skills,
    move_skill,
    valid_name,
)
from nestd.errors import ConflictError, InvalidInputError
from nestd.providers.codex_rpc import CodexRpc, JsonObject

logger = logging.getLogger(__name__)

NOT_SIGNED_IN = "{name} is not signed in"


@dataclass(frozen=True)
class Sources:
    """Where the page learns what is not in the engines' files."""

    claude: EngineProbe
    codex: EngineProbe
    # Enabled Claude plugins and their folders, by plugin name.
    plugin_folders: Callable[[], Awaitable[list[tuple[str, Path]]]]
    # How many claude.ai connectors Claude reported.
    connectors: Callable[[], Awaitable[int]]
    settings: Callable[[], ConfigurationSettings]
    save_settings: Callable[[ConfigurationSettings], ConfigurationSettings]
    # Every registered repo's folder, for the allow-list.
    repo_paths: Callable[[], list[Path]]
    # Whether local models are in use (B106): both engines' setups then show, since
    # either runs local chats without a sign in.
    local_in_use: Callable[[], Awaitable[bool]]


class Configuration:
    def __init__(
        self, where: Locations | None, backups: Backups, codex: CodexSetup, sources: Sources
    ) -> None:
        """`where` is None when Nest was started without an engine's folder (tests)."""
        self._where_or_none = where
        self.backups = backups
        self.codex = codex
        self._sources = sources
        self.lock = asyncio.Lock()

    @property
    def where(self) -> Locations:
        if self._where_or_none is None:
            msg = "Nest has no Claude or Codex folder to configure"
            raise ConfigurationUnavailableError(msg)
        return self._where_or_none

    async def page(self) -> ConfigurationPage:
        facts = await self.facts(full=True)
        return await asyncio.to_thread(build_page, facts)

    async def facts(self, *, full: bool = False) -> Facts:
        """What is true now; `full` also asks what only the page shows (versions, plugins,
        hooks, connectors).
        """
        where = self.where
        sources = self._sources
        claude = await sources.claude.account()
        codex = await sources.codex.account()
        local = await sources.local_in_use()
        state = State(
            where=where,
            settings=sources.settings(),
            claude=None if claude.signed_in is False and not local else claude,
            codex=codex if codex.signed_in is True or local else None,
        )
        if state.codex is not None:
            state = replace(state, codex_view=await self._codex_view(full=full))
        folders = await sources.plugin_folders()
        state = replace(state, plugin_skills=await asyncio.to_thread(_plugin_skills, folders))
        if full:
            state = replace(
                state,
                connectors=await sources.connectors(),
                claude_versions=await sources.claude.versions(),
                codex_versions=None if state.codex is None else await sources.codex.versions(),
            )
        return Facts(state)

    async def _codex_view(self, *, full: bool) -> CodexView:
        async def read(rpc: CodexRpc) -> CodexView:
            skills = await codex_api.list_skills(rpc)
            config = await codex_api.read_user_config(rpc)
            if not full:
                return CodexView(skills, config)
            plugins = await codex_api.installed_count(rpc)
            return CodexView(skills, config, plugins, await codex_api.user_hooks(rpc))

        try:
            return await self.codex.ask(read)
        except CodexSetupError as error:
            logger.warning("could not ask Codex for its setup: %s", error)
            return CodexView()

    # Files

    async def read_file(self, raw: str) -> FileText:
        path = self.where.readable(raw, self._sources.repo_paths())
        text = await asyncio.to_thread(read_text, path)
        return FileText(path=raw, text=text, version=await asyncio.to_thread(file_version, path))

    async def write_file(self, raw: str, text: str, expected: str | None) -> FileVersion:
        """409 with the version on disk when the file changed since `expected` (None: the
        client saw no file). Codex's config.toml must parse (422 naming the line); Nest's
        own MCP changes to it go through Codex instead.
        """
        path = self.where.writable(raw, self._sources.repo_paths())
        if path == self.where.codex_config.resolve():
            _require_toml(text)
        async with self.lock:
            current = await asyncio.to_thread(file_version, path)
            if current != expected:
                msg = f"{raw} changed on disk"
                raise ChangedOnDiskError(msg, current)
            backup = self.backups.start("file")
            version = await asyncio.to_thread(_backed_up_write, backup, path, text)
        return FileVersion(version=version)

    # Uses shared

    async def set_uses_shared(
        self, engine: EngineId, item: SharedItem, on: bool
    ) -> ConfigurationPage:
        """422 for a fixed switch, 404 for an engine not signed in."""
        if (engine, item) in {("claude", "skills"), ("codex", "instructions")}:
            msg = f"{engine}'s {item} are always the shared ones"
            raise InvalidInputError(msg)
        async with self.lock:
            facts = await self.facts()
            if engine not in facts.shown:
                raise UnknownItemError(NOT_SIGNED_IN.format(name=engine.capitalize()))
            if item == "mcp_servers":
                current = self._sources.settings()
                sharing = current.mcp_shared.model_copy(update={engine: on})
                self._sources.save_settings(current.model_copy(update={"mcp_shared": sharing}))
            elif engine == "claude":
                await asyncio.to_thread(self._import_shared, on)
            elif on:
                await self.link_codex_skills()
            else:
                await asyncio.to_thread(self._unlink_codex_skills)
        return await self.page()

    def _import_shared(self, on: bool) -> None:
        where = self.where
        backup = self.backups.start("instructions")
        text = read_text(where.claude_md)
        line = where.import_line()
        changed = with_import(text, line) if on else without_import(text, line)
        if on and not where.shared_instructions.exists():
            _backed_up_write(backup, where.shared_instructions, "")
        if changed != text:
            _backed_up_write(backup, where.claude_md, changed)

    async def link_codex_skills(self, backup: Backup | None = None) -> None:
        """Point Codex at the shared skills; the first time, the Claude-only claude.ai
        skills are switched off for Codex. 409 when something else has the link's name.
        """
        where = self.where
        link = where.skills_link
        if link.is_symlink() and link.resolve() == where.shared_skills.resolve():
            return
        if link.exists() or link.is_symlink():
            msg = f"{link} exists and is not Nest's link to the shared skills"
            raise ConflictError(msg)
        backup = backup or self.backups.start("skills-link")
        backup.save(link)
        where.shared_skills.mkdir(parents=True, exist_ok=True)
        where.codex_skills.mkdir(parents=True, exist_ok=True)
        link.symlink_to(where.shared_skills)
        settings = self._sources.settings()
        if settings.codex_claude_only_off:
            return
        await self.codex.ask(self._switch_off_claude_only)
        self._sources.save_settings(settings.model_copy(update={"codex_claude_only_off": True}))

    async def _switch_off_claude_only(self, rpc: CodexRpc) -> None:
        synced = self.where.synced_skills.resolve()
        for skill in (await codex_api.list_skills(rpc)).skills:
            real = skill.path.resolve()
            if synced in real.parents and real.parent.name in CLAUDE_ONLY:
                await codex_api.set_skill_enabled(rpc, skill.path, False)

    def _unlink_codex_skills(self) -> None:
        link = self.where.skills_link
        if not link.is_symlink():
            return
        if link.resolve() != self.where.shared_skills.resolve():
            msg = f"{link} is not Nest's link to the shared skills"
            raise ConflictError(msg)
        self.backups.start("skills-link").save(link)
        link.unlink()

    # Skills

    async def create_skill(self, name: str, description: str) -> ConfigurationPage:
        """422 for a name Claude would not take, 409 when it exists."""
        if not valid_name(name):
            msg = f"{name!r} is not a skill name: lowercase letters, digits and dashes"
            raise InvalidInputError(msg)
        async with self.lock:
            folder = self.where.shared_skills / name
            self.backups.start("new-skill").save(folder)
            await asyncio.to_thread(create_skill, self.where.shared_skills, name, description)
        return await self.page()

    async def delete_skill(self, name: str) -> ConfigurationPage:
        """Only the user's own skills; 403 for a read-only one, 404 for none."""
        async with self.lock:
            facts = await self.facts()
            items = [item for item in skill_items(facts) if item.name == name]
            if not items:
                raise UnknownItemError(f"no skill {name!r}")
            mine = next((item for item in items if item.source == "yours"), None)
            if mine is None:
                msg = f"{name} is read only here"
                raise PathNotAllowedError(msg)
            folder = self.where.writable(Path(mine.path).parent)
            backup = self.backups.start("delete-skill")
            await asyncio.to_thread(backup.save, folder)
            await asyncio.to_thread(remove, folder)
        return await self.page()

    async def make_shared(self, name: str) -> ConfigurationPage:
        """Move a Codex-only skill into the shared folder; Codex is pointed at it first."""
        async with self.lock:
            facts = await self.facts()
            backup = self.backups.start("make-shared")
            await self.share_codex_skill(facts, name, backup)
        return await self.page()

    async def share_codex_skill(self, facts: Facts, name: str, backup: Backup) -> None:
        if "codex" not in facts.shown:
            raise UnknownItemError(NOT_SIGNED_IN.format(name="Codex"))
        skill = next((s for s in facts.engine_only if s.path.parent.name == name), None)
        if skill is None:
            raise UnknownItemError(f"Codex has no skill {name!r} of its own")
        folder = skill.path.parent
        self.where.writable(folder.parent)
        destination = self.where.shared_skills / name
        if destination.exists() or destination.is_symlink():
            msg = f"the shared skills have a {name!r} already"
            raise ConflictError(msg)
        await self.link_codex_skills(backup)
        backup.save(folder)
        backup.save(destination)
        await asyncio.to_thread(move_skill, folder, destination)

    async def set_codex_skill(self, name: str, enabled: bool) -> ConfigurationPage:
        """Switch a skill on or off for Codex; 409 when Codex does not load it."""
        async with self.lock:
            facts = await self.facts()
            if "codex" not in facts.shown:
                raise UnknownItemError(NOT_SIGNED_IN.format(name="Codex"))
            items = [i for i in skill_items(facts) if i.name == name]
            if not items:
                raise UnknownItemError(f"no skill {name!r}")
            listed = [facts.codex_skill(Path(item.path)) for item in items]
            seen = [skill for skill in listed if skill is not None]
            if not seen:
                msg = f"Codex does not load {name}"
                raise ConflictError(msg)

            async def write(rpc: CodexRpc) -> None:
                for skill in seen:
                    await codex_api.set_skill_enabled(rpc, skill.path, enabled)

            await self.codex.ask(write)
        return await self.page()

    # MCP servers

    async def server(self, name: str) -> McpServer:
        facts = await self.facts()
        found = facts.server(name)
        if found is None:
            raise UnknownItemError(f"no MCP server {name!r}")
        return found

    async def put_server(self, name: str, server: McpServer) -> ConfigurationPage:
        """Into every engine whose MCP sharing is on; Codex only when it can take it."""
        async with self.lock:
            facts = await self.facts()
            table, _reason = to_codex(server)
            targets: list[EngineId] = [
                e for e in facts.sharing if e == "claude" or table is not None
            ]
            if not targets:
                msg = "no engine that shares MCP servers can take this server"
                raise InvalidInputError(msg)
            backup = self.backups.start("mcp-server")
            puts: dict[EngineId, dict[str, McpServer | None]] = {e: {name: server} for e in targets}
            await self.write_servers(backup, puts)
        return await self.page()

    async def delete_server(self, name: str) -> ConfigurationPage:
        async with self.lock:
            facts = await self.facts()
            targets: list[EngineId] = [e for e in facts.sharing if name in facts.servers(e)]
            if not targets:
                raise UnknownItemError(f"no shared MCP server {name!r}")
            backup = self.backups.start("mcp-server")
            drops: dict[EngineId, dict[str, McpServer | None]] = {e: {name: None} for e in targets}
            await self.write_servers(backup, drops)
        return await self.page()

    async def write_servers(
        self, backup: Backup, changes: dict[EngineId, dict[str, McpServer | None]]
    ) -> None:
        """Put (or with None remove) servers in each engine's own config, after a backup
        of the file (kept, never restored: the engines write other parts of it).
        """
        for engine, servers in changes.items():
            if engine == "claude":
                await asyncio.to_thread(self._write_claude_servers, backup, servers)
                continue
            backup.save(self.where.codex_config, restore=False)
            tables: dict[str, JsonObject | None] = {
                name: None if server is None else to_codex(server)[0]
                for name, server in servers.items()
            }
            await self.codex.ask(partial(codex_api.write_servers, changes=tables))

    def _write_claude_servers(self, backup: Backup, servers: dict[str, McpServer | None]) -> None:
        backup.save(self.where.claude_json, restore=False)
        file = ServersFile(self.where.claude_json)
        for name, server in servers.items():
            if server is None:
                file.remove(name)
            else:
                file.put(name, server)


def prepare_engine(where: Locations, engine: EngineId) -> None:
    """The engine's standard files and folders after it signed in (contract rule 4): only
    what is missing is created, empty.
    """
    if engine == "claude":
        where.shared_skills.mkdir(parents=True, exist_ok=True)
        return
    where.codex_home.mkdir(parents=True, exist_ok=True)
    if not where.shared_instructions.exists():
        write_text(where.shared_instructions, "")


def _require_toml(text: str) -> None:
    try:
        tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        msg = f"config.toml is not valid TOML: {error}"
        raise InvalidInputError(msg) from error


def _backed_up_write(backup: Backup, path: Path, text: str) -> str:
    backup.save(path)
    return write_text(path, text)


def _plugin_skills(folders: list[tuple[str, Path]]) -> list[tuple[str, FoundSkill]]:
    return [(name, skill) for name, folder in folders for skill in find_skills(folder / "skills")]
