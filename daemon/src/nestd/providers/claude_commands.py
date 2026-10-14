"""Slash commands, agents and context usage as Claude Code reports them (D032).

Commands with descriptions come from the initialize response and from `commands_changed`
system messages; the init message only names them, so its list completes the known one.
"""

from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from nestd.providers.base import AgentInfo, CommandCatalog, ContextUsage, SlashCommand

# Names starting with this are the engine's internal commands, never typed by users.
_INTERNAL_PREFIX = "__"


class _Command(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str
    description: str | None = None
    argument_hint: str | None = Field(default=None, alias="argumentHint")


class _Agent(BaseModel):
    name: str
    description: str | None = None


class _Context(BaseModel):
    percentage: float
    total_tokens: int = Field(alias="totalTokens")
    max_tokens: int = Field(alias="maxTokens")


def described_catalog(data: dict[str, Any] | None) -> CommandCatalog | None:
    """The commands and agents of an initialize response or a `commands_changed` message."""
    if data is None:
        return None
    commands = [
        SlashCommand(
            name=command.name,
            description=command.description or None,
            argument_hint=command.argument_hint or None,
        )
        for command in _parsed(data.get("commands"), _Command)
        if _usable(command.name)
    ]
    agents = [
        AgentInfo(name=agent.name, description=agent.description or None)
        for agent in _parsed(data.get("agents"), _Agent)
    ]
    if not commands and not agents:
        return None
    return sorted_catalog(CommandCatalog(commands=commands, agents=agents))


def init_catalog(data: dict[str, Any]) -> CommandCatalog | None:
    """The command, skill and agent names of the init message, without descriptions."""
    names = _strings(data.get("slash_commands")) + _strings(data.get("skills"))
    commands = [SlashCommand(name=name) for name in dict.fromkeys(names) if _usable(name)]
    agents = [AgentInfo(name=name) for name in dict.fromkeys(_strings(data.get("agents")))]
    if not commands and not agents:
        return None
    return sorted_catalog(CommandCatalog(commands=commands, agents=agents, partial=True))


def sorted_catalog(catalog: CommandCatalog) -> CommandCatalog:
    return catalog.model_copy(
        update={
            "commands": sorted(catalog.commands, key=lambda c: (c.name.lower(), c.name)),
            "agents": sorted(catalog.agents, key=lambda a: (a.name.lower(), a.name)),
        }
    )


def context_usage(raw: object) -> ContextUsage | None:
    """Percent used, tokens in context and the effective limit; None if they are missing."""
    try:
        usage = _Context.model_validate(raw)
    except ValidationError:
        return None
    return ContextUsage(percent=usage.percentage, used=usage.total_tokens, limit=usage.max_tokens)


def _usable(name: str) -> bool:
    return bool(name) and not name.startswith(_INTERNAL_PREFIX)


def _parsed[M: BaseModel](raw: object, model: type[M]) -> list[M]:
    """The entries of a JSON list that fit `model`; others are skipped."""
    entries = cast("list[object]", raw) if isinstance(raw, list) else []
    parsed: list[M] = []
    for entry in entries:
        try:
            parsed.append(model.model_validate(entry))
        except ValidationError:
            continue
    return parsed


def _strings(raw: object) -> list[str]:
    entries = cast("list[object]", raw) if isinstance(raw, list) else []
    return [entry for entry in entries if isinstance(entry, str)]
