"""Plugins, marketplaces and skills, through `claude plugin ...` (D104).

Every change goes through Claude Code's own commands, so it behaves as in Claude Code;
running chats pick changes up when their agent process next starts. `plugin details` has
no JSON output, so its text is read. A plugin not installed shows its components only when
its marketplace checkout holds it; plugins from other sources show none until installed.
"""

import asyncio
import re
from pathlib import Path
from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StringConstraints,
    TypeAdapter,
    ValidationError,
)

from nestd.claude_code.cli import ClaudeCli, ClaudeCliError
from nestd.errors import NotFoundError
from nestd.events import types
from nestd.events.bus import EventBus

_NAME = r"[A-Za-z0-9][A-Za-z0-9._-]*"
type PluginId = Annotated[str, StringConstraints(pattern=rf"^{_NAME}@{_NAME}$")]
type MarketplaceName = Annotated[str, StringConstraints(pattern=rf"^{_NAME}$")]
# A URL, path or GitHub repo; never something the CLI would read as an option.
type MarketplaceSource = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, pattern=r"^[^-\s]")
]
_COMPONENTS = {
    "Skills": "skills",
    "Agents": "agents",
    "Hooks": "hooks",
    "MCP servers": "mcp_servers",
    "LSP servers": "lsp_servers",
}
_COMPONENT_LINE = re.compile(r"^\s*(Skills|Agents|Hooks|MCP servers|LSP servers) \((\d+)\)\s*(.*)$")


class PluginNotFoundError(NotFoundError):
    pass


class InstalledPlugin(BaseModel):
    id: str
    name: str
    marketplace: str
    version: str | None
    enabled: bool
    # Where it is installed: "user", "project" or "local".
    scope: str
    # From the plugin's manifest; None when it has none.
    description: str | None


class Skill(BaseModel):
    """A standalone skill in `~/.claude/skills`, listed read-only."""

    name: str
    description: str | None
    path: str


class PixieSkill(BaseModel):
    """A skill a pixie can be given (D109): a standalone one by its name, or a plugin's as
    `<plugin>:<skill>`, the name Claude Code and the SDK's `skills` option use.
    """

    name: str
    description: str | None
    # The plugin's name; None for a standalone skill.
    plugin: str | None


class Marketplace(BaseModel):
    name: str
    # The CLI's source kind, such as "github", "git", "url" or "directory".
    kind: str
    # Its repo, URL or path, when the CLI says.
    source: str | None


class AvailablePlugin(BaseModel):
    id: str
    name: str
    marketplace: str
    description: str | None
    version: str | None
    # Where it comes from: a path in its marketplace, a URL or a package.
    source: str
    install_count: int | None
    installed: bool


class Components(BaseModel):
    count: int
    names: list[str]


class PluginDetails(BaseModel):
    id: str
    name: str
    marketplace: str
    description: str | None
    source: str
    installed: bool
    # Keys skills, agents, hooks, mcp_servers and lsp_servers; None when unknown (a plugin
    # from outside its marketplace's checkout, before it is installed).
    components: dict[str, Components] | None


class _Installed(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: PluginId
    version: str | None = None
    scope: str = "user"
    enabled: bool = True
    install_path: str | None = Field(default=None, alias="installPath")


class _Available(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: PluginId = Field(alias="pluginId")
    name: str
    marketplace: str = Field(alias="marketplaceName")
    description: str | None = None
    version: str | None = None
    source: str | dict[str, JsonValue]
    install_count: int | None = Field(default=None, alias="installCount")


class _Listing(BaseModel):
    installed: list[_Installed]
    available: list[_Available]


class _Marketplace(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str
    source: str
    repo: str | None = None
    url: str | None = None
    path: str | None = None
    install_location: str | None = Field(default=None, alias="installLocation")


class Extensions:
    def __init__(self, cli: ClaudeCli, bus: EventBus, claude_dir: Path | None) -> None:
        """`claude_dir` holds the standalone skills; None lists none."""
        self._cli = cli
        self._bus = bus
        self._claude_dir = claude_dir

    async def plugins(self) -> list[InstalledPlugin]:
        raw = await self._json(["plugin", "list", "--json"], list[_Installed])
        return [await self._installed(plugin) for plugin in raw]

    async def skills(self) -> list[Skill]:
        if self._claude_dir is None:
            return []
        return await asyncio.to_thread(_read_skills, self._claude_dir / "skills")

    async def pixie_skills(self) -> list[PixieSkill]:
        """Standalone skills and the skills of every enabled plugin, by name."""
        skills = [
            PixieSkill(name=skill.name, description=skill.description, plugin=None)
            for skill in await self.skills()
        ]
        plugins = await self._json(["plugin", "list", "--json"], list[_Installed])
        found = await asyncio.gather(
            *(self._plugin_skills(plugin) for plugin in plugins if plugin.enabled)
        )
        skills += [skill for group in found for skill in group]
        return sorted(skills, key=lambda skill: skill.name)

    async def plugin_folders(self) -> list[tuple[str, Path]]:
        """Each enabled plugin's name and installed folder (B97), for its skills."""
        plugins = await self._json(["plugin", "list", "--json"], list[_Installed])
        return [
            (plugin.id.split("@", 1)[0], Path(plugin.install_path))
            for plugin in plugins
            if plugin.enabled and plugin.install_path is not None
        ]

    async def _plugin_skills(self, plugin: _Installed) -> list[PixieSkill]:
        """Its skills as `plugin details` lists them (commands included, and only the
        skills its marketplace entry names); its folder's skills when that fails.
        """
        name = plugin.id.split("@", 1)[0]
        folder = None if plugin.install_path is None else Path(plugin.install_path)
        descriptions = {} if folder is None else await asyncio.to_thread(_descriptions, folder)
        try:
            output = await self._cli.run(["plugin", "details", plugin.id])
            names = parse_details(output)[1]["skills"].names
        except ClaudeCliError:
            names = sorted(descriptions)
        return [
            PixieSkill(name=f"{name}:{skill}", description=descriptions.get(skill), plugin=name)
            for skill in names
        ]

    async def marketplaces(self) -> list[Marketplace]:
        raw = await self._marketplaces()
        return [
            Marketplace(name=m.name, kind=m.source, source=m.repo or m.url or m.path) for m in raw
        ]

    async def add_marketplace(self, source: MarketplaceSource) -> None:
        await self._change(["plugin", "marketplace", "add", "--", source])

    async def remove_marketplace(self, name: MarketplaceName) -> None:
        await self._change(["plugin", "marketplace", "remove", name])

    async def available(self) -> list[AvailablePlugin]:
        listing = await self._listing()
        plugins = [_offered(plugin) for plugin in listing.available]
        for plugin in listing.installed:
            name, marketplace = plugin.id.split("@", 1)
            plugins.append(
                AvailablePlugin(
                    id=plugin.id,
                    name=name,
                    marketplace=marketplace,
                    description=await _manifest_description(plugin.install_path),
                    version=plugin.version,
                    source=marketplace,
                    install_count=None,
                    installed=True,
                )
            )
        return sorted(plugins, key=lambda plugin: plugin.id)

    async def details(self, plugin_id: PluginId) -> PluginDetails:
        name, marketplace = plugin_id.split("@", 1)
        listing = await self._listing()
        if any(plugin.id == plugin_id for plugin in listing.installed):
            description, components = parse_details(
                await self._cli.run(["plugin", "details", plugin_id])
            )
            return PluginDetails(
                id=plugin_id,
                name=name,
                marketplace=marketplace,
                description=description,
                source=marketplace,
                installed=True,
                components=components,
            )
        offered = next((p for p in listing.available if p.id == plugin_id), None)
        if offered is None:
            msg = f"no plugin {plugin_id!r} in the configured marketplaces"
            raise PluginNotFoundError(msg)
        components = None
        folder = await self._checkout_folder(offered)
        if folder is not None:
            output = await self._cli.run(
                ["--plugin-dir", str(folder), "plugin", "details", offered.name]
            )
            components = parse_details(output)[1]
        plugin = _offered(offered)
        return PluginDetails(
            id=plugin_id,
            name=plugin.name,
            marketplace=plugin.marketplace,
            description=plugin.description,
            source=plugin.source,
            installed=False,
            components=components,
        )

    async def install(self, plugin_id: PluginId) -> None:
        await self._change(["plugin", "install", plugin_id], long=True)

    async def uninstall(self, plugin_id: PluginId) -> None:
        await self._change(["plugin", "uninstall", plugin_id])

    async def set_enabled(self, plugin_id: PluginId, enabled: bool) -> None:
        await self._change(["plugin", "enable" if enabled else "disable", plugin_id])

    async def _change(self, args: list[str], *, long: bool = False) -> None:
        await self._cli.run(args, long=long)
        await self._bus.publish(types.EXTENSIONS_UPDATED, {})

    async def _listing(self) -> _Listing:
        return await self._json(["plugin", "list", "--json", "--available"], _Listing)

    async def _marketplaces(self) -> list[_Marketplace]:
        return await self._json(["plugin", "marketplace", "list", "--json"], list[_Marketplace])

    async def _json[T](self, args: list[str], shape: type[T]) -> T:
        output = await self._cli.run(args)
        try:
            return TypeAdapter(shape).validate_json(output)
        except ValidationError as error:
            msg = f"claude {' '.join(args)} gave unexpected output"
            raise ClaudeCliError(msg) from error

    async def _installed(self, plugin: _Installed) -> InstalledPlugin:
        name, marketplace = plugin.id.split("@", 1)
        return InstalledPlugin(
            id=plugin.id,
            name=name,
            marketplace=marketplace,
            version=plugin.version,
            enabled=plugin.enabled,
            scope=plugin.scope,
            description=await _manifest_description(plugin.install_path),
        )

    async def _checkout_folder(self, plugin: _Available) -> Path | None:
        """The plugin's folder in its marketplace's checkout, when it has one there."""
        if not isinstance(plugin.source, str):
            return None
        for marketplace in await self._marketplaces():
            if marketplace.name == plugin.marketplace and marketplace.install_location:
                folder = Path(marketplace.install_location) / plugin.source
                if await asyncio.to_thread(folder.is_dir):
                    return folder
        return None


def parse_details(text: str) -> tuple[str | None, dict[str, Components]]:
    """The description and component inventory from `claude plugin details`."""
    description = None
    components = {key: Components(count=0, names=[]) for key in _COMPONENTS.values()}
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("Description:") and description is None:
            description = stripped.removeprefix("Description:").strip() or None
        match = _COMPONENT_LINE.match(line)
        if match is not None:
            listed = re.split(r"\s{2,}\(", match[3])[0]
            names = [name.strip() for name in listed.split(",") if name.strip()]
            components[_COMPONENTS[match[1]]] = Components(count=int(match[2]), names=names)
    return description, components


def _offered(plugin: _Available) -> AvailablePlugin:
    source = plugin.source
    if isinstance(source, dict):
        parts = [source.get(key) for key in ("url", "repo", "package", "path")]
        source = " ".join(part for part in parts if isinstance(part, str))
    return AvailablePlugin(
        id=plugin.id,
        name=plugin.name,
        marketplace=plugin.marketplace,
        description=plugin.description,
        version=plugin.version,
        source=source,
        install_count=plugin.install_count,
        installed=False,
    )


async def _manifest_description(install_path: str | None) -> str | None:
    if install_path is None:
        return None
    return await asyncio.to_thread(_read_description, Path(install_path))


class _Manifest(BaseModel):
    description: str | None = None


def _read_description(folder: Path) -> str | None:
    try:
        text = (folder / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
        return _Manifest.model_validate_json(text).description
    except (OSError, ValidationError):
        return None


def _read_skills(folder: Path) -> list[Skill]:
    skills: list[Skill] = []
    if not folder.is_dir():
        return skills
    for entry in sorted(folder.iterdir()):
        file = entry / "SKILL.md"
        if not file.is_file():
            continue
        fields = front_matter(file.read_text(encoding="utf-8", errors="replace"))
        skills.append(
            Skill(
                name=fields.get("name") or entry.name,
                description=fields.get("description"),
                path=str(entry),
            )
        )
    return sorted(skills, key=lambda skill: skill.name)


def _descriptions(folder: Path) -> dict[str, str | None]:
    """A plugin folder's skills (`skills/<name>/SKILL.md`) and commands
    (`commands/<name>.md`) with their descriptions; what cannot be read is left out.
    """
    found: dict[str, str | None] = {}
    try:
        for skill in _read_skills(folder / "skills"):
            found[skill.name] = skill.description
    except OSError:
        pass
    try:
        for file in sorted((folder / "commands").iterdir()):
            if file.suffix != ".md":
                continue
            text = file.read_text(encoding="utf-8", errors="replace")
            found.setdefault(file.stem, front_matter(text).get("description"))
    except OSError:
        pass
    return found


def front_matter(text: str) -> dict[str, str]:
    """`key: value` lines between the opening and closing `---`; nothing when unclosed."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    fields: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            return fields
        key, colon, value = line.partition(":")
        if colon and value.strip():
            fields[key.strip()] = _scalar(value.strip())
    return {}


# YAML's double-quoted escapes Nest reads; `\uXXXX` is handled apart.
_ESCAPES = {'"': '"', "\\": "\\", "/": "/", "n": "\n", "t": "\t", "r": "\r", "0": "\0"}


def _scalar(value: str) -> str:
    """A quoted value up to its closing quote, unescaped as YAML does; anything after it
    (a comment) is dropped. An unquoted value, or one never closed, only loses quote marks
    at its ends.
    """
    if value[0] == "'":
        closed = _single_quoted(value)
    elif value[0] == '"':
        closed = _double_quoted(value)
    else:
        closed = None
    return value.strip("\"'") if closed is None else closed


def _single_quoted(value: str) -> str | None:
    text: list[str] = []
    index = 1
    while index < len(value):
        char = value[index]
        if char == "'":
            if value[index + 1 : index + 2] != "'":
                return "".join(text)
            index += 1
        text.append(char)
        index += 1
    return None


def _double_quoted(value: str) -> str | None:
    text: list[str] = []
    index = 1
    while index < len(value):
        char = value[index]
        if char == '"':
            return "".join(text)
        if char == "\\" and index + 1 < len(value):
            code = value[index + 1]
            if code == "u" and _hex(value[index + 2 : index + 6]):
                text.append(chr(int(value[index + 2 : index + 6], 16)))
                index += 6
                continue
            text.append(_ESCAPES.get(code, code))
            index += 2
            continue
        text.append(char)
        index += 1
    return None


def _hex(digits: str) -> bool:
    return len(digits) == 4 and all(c in "0123456789abcdefABCDEF" for c in digits)
