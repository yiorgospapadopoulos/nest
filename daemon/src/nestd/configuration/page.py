"""What the engines' files and Codex say now, and the page built from it (B97)."""

from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

from nestd.config.models import ConfigurationSettings
from nestd.configuration.codex import CodexSkill, CodexSkills, CodexUserConfig
from nestd.configuration.engines import EngineAccount, Versions, claude_items, codex_items
from nestd.configuration.errors import PathNotAllowedError
from nestd.configuration.files import file_version, read_text
from nestd.configuration.instructions import has_import, own_instructions
from nestd.configuration.locations import Locations
from nestd.configuration.mcp import (
    McpServer,
    ServersFile,
    claude_problem,
    from_codex,
    to_codex,
)
from nestd.configuration.models import (
    ConfigurationPage,
    EngineId,
    EngineSection,
    InstructionsFile,
    MissingFromShared,
    Shared,
    SharedServer,
    SharedSkills,
    SkillItem,
    Switch,
    UsesShared,
)
from nestd.configuration.skills import FoundSkill, find_skills

ENGINE_NAMES: dict[EngineId, str] = {"claude": "Claude", "codex": "Codex"}


@dataclass(frozen=True)
class CodexView:
    """What a signed-in Codex reports; empty when it could not be asked."""

    skills: CodexSkills = field(default_factory=CodexSkills)
    config: CodexUserConfig = field(default_factory=CodexUserConfig)
    plugins: int = 0
    hooks: int = 0


@dataclass(frozen=True)
class ServerSplit:
    add: list[str] = field(default_factory=list[str])
    already: list[str] = field(default_factory=list[str])
    # Name and why the other engine cannot take it.
    not_convertible: list[tuple[str, str]] = field(default_factory=list[tuple[str, str]])


@dataclass(frozen=True)
class State:
    where: Locations
    settings: ConfigurationSettings
    # None for an engine that is not shown (not signed in).
    claude: EngineAccount | None
    codex: EngineAccount | None
    codex_view: CodexView | None = None
    # Enabled Claude plugins' skills, with the plugin's name.
    plugin_skills: list[tuple[str, FoundSkill]] = field(
        default_factory=list[tuple[str, FoundSkill]]
    )
    connectors: int = 0
    claude_versions: Versions | None = None
    codex_versions: Versions | None = None


class Facts:
    """The state read from disk once; every question the page and the copy ask."""

    def __init__(self, state: State) -> None:
        self.state = state
        self.where = state.where

    @cached_property
    def shown(self) -> list[EngineId]:
        engines: list[EngineId] = []
        if self.state.claude is not None:
            engines.append("claude")
        if self.state.codex is not None:
            engines.append("codex")
        return engines

    @cached_property
    def shared_skills(self) -> list[FoundSkill]:
        return find_skills(self.where.shared_skills)

    @cached_property
    def claude_md(self) -> str:
        return read_text(self.where.claude_md)

    @cached_property
    def shared_text(self) -> str:
        return read_text(self.where.shared_instructions)

    @cached_property
    def claude_imports(self) -> bool:
        return has_import(self.claude_md, self.where.import_line())

    @cached_property
    def claude_own(self) -> str:
        return own_instructions(self.claude_md, self.where.import_line())

    @cached_property
    def claude_instructions_missing(self) -> bool:
        own = self.claude_own
        return bool(own) and own != self.shared_text.strip() and not self.claude_imports

    @cached_property
    def link_on(self) -> bool:
        link = self.where.skills_link
        return link.is_symlink() and link.resolve() == self.where.shared_skills.resolve()

    @cached_property
    def codex_skills(self) -> CodexSkills:
        view = self.state.codex_view
        return CodexSkills() if view is None else view.skills

    @cached_property
    def codex_by_path(self) -> dict[Path, CodexSkill]:
        return {skill.path.resolve(): skill for skill in self.codex_skills.skills}

    @cached_property
    def codex_errors(self) -> dict[Path, str]:
        """Why Codex could not load a SKILL.md, by its real path."""
        return {path.resolve(): error for path, error in self.codex_skills.errors.items()}

    def codex_skill(self, path: Path) -> CodexSkill | None:
        """How Codex lists the SKILL.md at `path`, maybe through a link."""
        return self.codex_by_path.get(path.resolve())

    @cached_property
    def engine_only(self) -> list[CodexSkill]:
        """Codex's own skills (the user's, not a plugin's) outside the shared folder."""
        shared = self.where.shared_skills.resolve()
        return [
            skill
            for skill in self.codex_skills.skills
            if skill.scope == "user"
            and skill.plugin_id is None
            and shared not in skill.path.resolve().parents
        ]

    @cached_property
    def plugin_skill_names(self) -> dict[str, str]:
        """Claude's plugin skills by name, with the plugin's name."""
        return {skill.name: plugin for plugin, skill in self.state.plugin_skills}

    @cached_property
    def missing_codex_skills(self) -> list[str]:
        """Codex's own skills that Claude has neither shared nor from a plugin."""
        shared = {skill.name for skill in self.shared_skills}
        names = {skill.path.parent.name for skill in self.engine_only}
        return sorted(names - shared - set(self.plugin_skill_names))

    def server_split(self, engine: EngineId) -> ServerSplit:
        """The engine's servers as a copy to Shared sees them: added to the other sharing
        engines, there already, or not convertible for the other engine.
        """
        others: list[EngineId] = [other for other in self.sharing if other != engine]
        target: EngineId = "codex" if engine == "claude" else "claude"
        split = ServerSplit()
        for name, server in sorted(self.servers(engine).items()):
            reason = to_codex(server)[1] if engine == "claude" else claude_problem(server)
            if reason is not None and target in others:
                split.not_convertible.append((name, reason))
            elif all(name in self.servers(other) for other in others):
                split.already.append(name)
            else:
                split.add.append(name)
        return split

    def servers(self, engine: EngineId) -> dict[str, McpServer]:
        return self.claude_servers if engine == "claude" else self.codex_servers

    @cached_property
    def claude_servers(self) -> dict[str, McpServer]:
        if self.state.claude is None:
            return {}
        return ServersFile(self.where.claude_json).servers()

    @cached_property
    def codex_servers(self) -> dict[str, McpServer]:
        view = self.state.codex_view
        tables = {} if view is None else view.config.servers
        found = {name: from_codex(table) for name, table in tables.items()}
        return {name: server for name, server in found.items() if server is not None}

    @cached_property
    def sharing(self) -> list[EngineId]:
        """The shown engines whose MCP servers are shared."""
        shared = self.state.settings.mcp_shared
        return [engine for engine in self.shown if getattr(shared, engine)]

    @cached_property
    def shared_names(self) -> list[str]:
        return sorted({name for engine in self.sharing for name in self.servers(engine)})

    def server(self, name: str) -> McpServer | None:
        """Claude's when it has it, else Codex's."""
        return self.claude_servers.get(name) or self.codex_servers.get(name)

    def writable(self, path: Path) -> bool:
        try:
            self.where.writable(path)
        except PathNotAllowedError:
            return False
        return True


def build_page(facts: Facts) -> ConfigurationPage:
    return ConfigurationPage(
        shared=Shared(
            instructions=InstructionsFile(
                path=str(facts.where.shared_instructions),
                exists=facts.where.shared_instructions.is_file(),
                version=file_version(facts.where.shared_instructions),
            ),
            skills=SharedSkills(folder=str(facts.where.shared_skills), items=skill_items(facts)),
            mcp_servers=[_shared_server(facts, name) for name in facts.shared_names],
        ),
        engines=[_section(facts, engine) for engine in facts.shown],
    )


def skill_items(facts: Facts) -> list[SkillItem]:
    # Whether Codex loads a shared skill is known only while it uses the shared folder.
    codex_uses = facts.state.codex is not None and facts.link_on
    synced = facts.where.synced_skills
    items: list[SkillItem] = []
    for skill in facts.shared_skills:
        real = skill.file.resolve()
        listed = facts.codex_by_path.get(real)
        is_synced = synced in skill.file.parents
        items.append(
            SkillItem(
                name=skill.name,
                description=skill.description,
                path=str(skill.file),
                source="synced" if is_synced else "yours",
                read_only=is_synced,
                codex_enabled=(listed is not None and listed.enabled) if codex_uses else None,
                codex_error=facts.codex_errors.get(real),
            )
        )
    items += [
        SkillItem(
            name=skill.path.parent.name,
            description=skill.description,
            path=str(skill.path),
            source="engine_only",
            engine="codex",
            read_only=not facts.writable(skill.path.parent),
            codex_enabled=skill.enabled,
        )
        for skill in facts.engine_only
    ]
    return items


def _shared_server(facts: Facts, name: str) -> SharedServer:
    server = facts.server(name)
    assert server is not None  # noqa: S101 (listed from the engines' servers)
    claude = facts.claude_servers.get(name)
    reason = claude_problem(server) if claude is None else to_codex(claude)[1]
    return SharedServer(
        name=name,
        summary=server.summary(),
        transport=server.transport,
        engines=[engine for engine in facts.shown if name in facts.servers(engine)],
        convertible=reason is None,
        reason=reason,
    )


def _section(facts: Facts, engine: EngineId) -> EngineSection:
    state = facts.state
    account = state.claude if engine == "claude" else state.codex
    versions = state.claude_versions if engine == "claude" else state.codex_versions
    sharing_mcp = Switch(on=getattr(state.settings.mcp_shared, engine), fixed=False)
    missing_servers = facts.server_split(engine).add
    if engine == "claude":
        uses = UsesShared(
            instructions=Switch(on=facts.claude_imports, fixed=False),
            skills=Switch(on=True, fixed=True),
            mcp_servers=sharing_mcp,
        )
        missing = MissingFromShared(
            instructions=facts.claude_instructions_missing, skills=[], mcp_servers=missing_servers
        )
        folder = facts.where.claude_dir
        items = claude_items(facts.where, state.connectors)
    else:
        view = state.codex_view or CodexView()
        uses = UsesShared(
            instructions=Switch(on=True, fixed=True),
            skills=Switch(on=facts.link_on, fixed=False),
            mcp_servers=sharing_mcp,
        )
        missing = MissingFromShared(
            instructions=False,
            skills=facts.missing_codex_skills,
            mcp_servers=missing_servers,
        )
        folder = facts.where.codex_home
        items = codex_items(facts.where, view.plugins, view.hooks)
    return EngineSection(
        id=engine,
        name=ENGINE_NAMES[engine],
        account=None if account is None else account.label,
        bundled_version=None if versions is None else versions.bundled,
        standalone=None if versions is None else versions.standalone,
        config_folder=str(folder),
        uses_shared=uses,
        missing_from_shared=missing,
        items=items,
    )
