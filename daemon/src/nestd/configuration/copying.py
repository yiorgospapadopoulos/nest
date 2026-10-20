"""Copy an engine's setup to Shared, and undo it (B97, plan scope 4).

Skills and MCP servers are added on top of Shared's: a name Shared has already keeps the
shared one and is listed as skipped. Only the instructions are replaced, and only when the
user leaves "Keep instructions as they are" off; the engine's own file then imports the
shared one. Everything touched is backed up first, and the backup is the undo.
"""

import asyncio

from nestd.configuration.errors import UnknownItemError
from nestd.configuration.files import write_text
from nestd.configuration.mcp import McpServer
from nestd.configuration.models import (
    ConfigurationPage,
    CopyPreview,
    CopyResult,
    EngineId,
    InstructionsPreview,
    NotConvertible,
    SameName,
    ServersPreview,
    SkillsPreview,
)
from nestd.configuration.page import Facts
from nestd.configuration.service import NOT_SIGNED_IN, Configuration

ENGINES: tuple[EngineId, ...] = ("claude", "codex")
SHARED_HAS_IT = "Shared has a skill with this name"
STAYS: dict[EngineId, list[str]] = {
    "claude": [
        "plugins themselves",
        "claude.ai connectors",
        "hooks",
        "subagents",
        "slash commands",
        "permission rules",
    ],
    "codex": ["plugins themselves", "hooks", "rules", "other config.toml settings"],
}


async def preview(configuration: Configuration, engine: EngineId) -> CopyPreview:
    facts = await configuration.facts()
    _require(facts, engine)
    return _preview(facts, engine)


async def copy(configuration: Configuration, engine: EngineId, instructions: bool) -> CopyResult:
    """`instructions` false keeps the shared instructions as they are."""
    async with configuration.lock:
        facts = await configuration.facts()
        _require(facts, engine)
        plan = _preview(facts, engine)
        where = configuration.where
        backup = configuration.backups.start(f"copy-{engine}")
        replaced = instructions and plan.instructions is not None
        if replaced:
            backup.save(where.shared_instructions)
            backup.save(where.claude_md)
            await asyncio.to_thread(write_text, where.shared_instructions, facts.claude_own + "\n")
            await asyncio.to_thread(write_text, where.claude_md, where.import_line() + "\n")
        for name in plan.skills.add:
            await configuration.share_codex_skill(facts, name, backup)
        added = _additions(facts, engine, plan.mcp_servers.add)
        await configuration.write_servers(backup, added)
        backup.finish_undoable({target: sorted(servers) for target, servers in added.items()})
    page = await configuration.page()
    summary = _summary(replaced, len(plan.skills.add), len(plan.mcp_servers.add))
    return CopyResult(summary=summary, undo_id=backup.id, page=page)


async def undo(configuration: Configuration, undo_id: str) -> ConfigurationPage:
    """404 for an unknown backup, 409 when a restored file changed since the copy."""
    async with configuration.lock:
        backup = configuration.backups.load(undo_id)
        await asyncio.to_thread(backup.restore)
        added = backup.added_servers
        removals: dict[EngineId, dict[str, McpServer | None]] = {
            target: dict.fromkeys(added[target]) for target in ENGINES if added.get(target)
        }
        removal_backup = configuration.backups.start("undo")
        await configuration.write_servers(removal_backup, removals)
    return await configuration.page()


def _require(facts: Facts, engine: EngineId) -> None:
    if engine not in facts.shown:
        raise UnknownItemError(NOT_SIGNED_IN.format(name=engine.capitalize()))


def _preview(facts: Facts, engine: EngineId) -> CopyPreview:
    shared_names = sorted({skill.name for skill in facts.shared_skills})
    if engine == "claude":
        instructions = None
        if facts.claude_instructions_missing:
            instructions = InstructionsPreview(
                replace=True,
                engine_path=str(facts.where.claude_md),
                shared_path=str(facts.where.shared_instructions),
            )
        skills = SkillsPreview(add=[], already=shared_names, same_name=[])
    else:
        instructions = None
        own = sorted({skill.path.parent.name for skill in facts.engine_only})
        same_name: list[SameName] = []
        for name in own:
            plugin = facts.plugin_skill_names.get(name)
            if name in shared_names:
                same_name.append(SameName(name=name, reason=SHARED_HAS_IT))
            elif plugin is not None:
                same_name.append(SameName(name=name, reason=f"Claude has it from plugin {plugin}"))
        skills = SkillsPreview(
            add=facts.missing_codex_skills,
            already=shared_names if facts.link_on else [],
            same_name=same_name,
        )
    return CopyPreview(
        instructions=instructions,
        skills=skills,
        mcp_servers=_servers_preview(facts, engine),
        stays=STAYS[engine],
    )


def _servers_preview(facts: Facts, engine: EngineId) -> ServersPreview:
    split = facts.server_split(engine)
    return ServersPreview(
        add=split.add,
        already=split.already,
        not_convertible=[
            NotConvertible(name=name, reason=reason) for name, reason in split.not_convertible
        ],
    )


def _additions(
    facts: Facts, engine: EngineId, names: list[str]
) -> dict[EngineId, dict[str, McpServer | None]]:
    """The servers to add to each other sharing engine that lacks them."""
    added: dict[EngineId, dict[str, McpServer | None]] = {}
    servers = facts.servers(engine)
    for other in facts.sharing:
        if other == engine:
            continue
        missing: dict[str, McpServer | None] = {
            name: servers[name] for name in names if name not in facts.servers(other)
        }
        if missing:
            added[other] = missing
    return added


def _summary(instructions: bool, skills: int, servers: int) -> str:
    parts: list[str] = []
    if instructions:
        parts.append("instructions replaced (backup kept)")
    counts = [
        _count(skills, "skill", "skills"),
        _count(servers, "MCP server", "MCP servers"),
    ]
    added = " and ".join(count for count in counts if count)
    if added:
        parts.append(f"{added} added")
    if not parts:
        return "Nothing to copy: Shared has all of it already."
    return f"Copied to Shared: {', '.join(parts)}."


def _count(count: int, one: str, many: str) -> str:
    if count == 0:
        return ""
    return f"{count} {one if count == 1 else many}"
