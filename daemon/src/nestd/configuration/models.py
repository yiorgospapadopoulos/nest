"""The configuration page and its parts as the API returns them (B97 contract)."""

from typing import Literal

from pydantic import BaseModel

from nestd.configuration.mcp import McpServerSummary, Transport

type EngineId = Literal["claude", "codex"]
type SharedItem = Literal["instructions", "skills", "mcp_servers"]
type SkillSource = Literal["yours", "synced", "plugin", "engine_only", "project"]
type ItemKind = Literal[
    "plugins", "connectors", "hooks", "subagents", "commands", "permissions", "settings", "rules"
]


class InstructionsFile(BaseModel):
    path: str
    exists: bool
    version: str | None


class SkillItem(BaseModel):
    name: str
    description: str | None
    # Its SKILL.md.
    path: str
    source: SkillSource
    plugin: str | None = None
    # The engine an `engine_only` skill is in.
    engine: EngineId | None = None
    read_only: bool
    # Whether Codex loads it; None when Codex is not shown or cannot see it at all.
    codex_enabled: bool | None = None
    # Why Codex cannot load it.
    codex_error: str | None = None


class SharedSkills(BaseModel):
    folder: str
    items: list[SkillItem]


class SharedServer(BaseModel):
    name: str
    summary: str
    transport: Transport
    engines: list[EngineId]
    convertible: bool
    reason: str | None


class Shared(BaseModel):
    instructions: InstructionsFile
    skills: SharedSkills
    mcp_servers: list[SharedServer]


class Switch(BaseModel):
    on: bool
    fixed: bool


class UsesShared(BaseModel):
    instructions: Switch
    skills: Switch
    mcp_servers: Switch


class MissingFromShared(BaseModel):
    instructions: bool
    skills: list[str]
    mcp_servers: list[str]


class EngineItem(BaseModel):
    kind: ItemKind
    count: int | None
    detail: str | None = None
    path: str | None = None
    folder: bool = False


class Standalone(BaseModel):
    path: str
    version: str | None


class EngineSection(BaseModel):
    id: EngineId
    name: str
    # Such as "me@example.com · Claude Max"; None when unknown.
    account: str | None
    bundled_version: str | None
    standalone: Standalone | None
    config_folder: str
    uses_shared: UsesShared
    missing_from_shared: MissingFromShared
    items: list[EngineItem]


class ConfigurationPage(BaseModel):
    shared: Shared
    engines: list[EngineSection]


class FileText(BaseModel):
    path: str
    text: str
    # sha256 of the bytes; None when there is no file yet.
    version: str | None


class FileVersion(BaseModel):
    version: str


class InstructionsPreview(BaseModel):
    replace: bool
    engine_path: str
    shared_path: str


class SameName(BaseModel):
    name: str
    # Why it is skipped, such as "Claude has it from plugin superpowers".
    reason: str


class SkillsPreview(BaseModel):
    add: list[str]
    already: list[str]
    same_name: list[SameName]


class NotConvertible(BaseModel):
    name: str
    reason: str


class ServersPreview(BaseModel):
    add: list[str]
    already: list[str]
    not_convertible: list[NotConvertible]


class CopyPreview(BaseModel):
    instructions: InstructionsPreview | None
    skills: SkillsPreview
    mcp_servers: ServersPreview
    stays: list[str]


class CopyResult(BaseModel):
    summary: str
    undo_id: str
    page: ConfigurationPage


class ProjectFile(BaseModel):
    path: str
    exists: bool


class ProjectConfiguration(BaseModel):
    instructions: list[ProjectFile]
    skills: list[SkillItem]
    mcp_servers: list[McpServerSummary]
