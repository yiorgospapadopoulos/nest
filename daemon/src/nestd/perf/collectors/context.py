"""Context cost (C5, live): what a new chat's context holds before any work, from one
small Claude turn in General on a one-off client set up exactly as a new Nest chat is
(Nest's prompt and tools, the user's settings, plugins and MCP servers) on Haiku. No chat
row is made and no transcript is kept.

Claude Code's breakdown (`get_context_usage`) names its categories; MCP tools that tool
search defers are reported apart, so one turn gives the cost with tool search and
without it. Nest's own parts are estimated from their text (four characters a token).
"""

import asyncio
import dataclasses
import json
from collections.abc import AsyncIterable, AsyncIterator, Awaitable, Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol, cast

from claude_agent_sdk import ClaudeAgentOptions, ContextUsageResponse, Message, ResultMessage
from pydantic import JsonValue

from nestd.perf.formatting import compact
from nestd.perf.models import Collected, Measured, Part
from nestd.providers.base import (
    AgentTool,
    RunAccount,
    SessionSpec,
)
from nestd.providers.claude import build_options
from nestd.providers.one_off import NoTools

MODEL = "haiku"
PROMPT = "Reply with OK"
TURN_SECONDS = 120.0
CHARS_PER_TOKEN = 4

# Claude Code's category names (its `/context` lines), to Nest's parts.
_SYSTEM_PROMPT = "System prompt"
_SYSTEM_TOOLS = "System tools"
_MCP_TOOLS = "MCP tools"
_MCP_INSTRUCTIONS = "MCP server instructions"
_MEMORY = "Memory files"
_SKILLS = "Skills"
_MESSAGES = "Messages"
_FREE = "Free space"


class ContextClient(Protocol):
    """The part of ClaudeSDKClient this uses; tests substitute a fake."""

    async def connect(self) -> None: ...

    async def query(
        self, prompt: str | AsyncIterable[dict[str, Any]], session_id: str = ...
    ) -> None: ...

    def receive_messages(self) -> AsyncIterator[Message]: ...

    async def get_context_usage(self) -> ContextUsageResponse: ...

    async def disconnect(self) -> None: ...


type ContextClientFactory = Callable[[ClaudeAgentOptions], ContextClient]


@dataclasses.dataclass(frozen=True)
class NewChat:
    """What a new chat in General gets from Nest."""

    folder: Path
    prompt: str
    tools: tuple[AgentTool, ...]
    gh_config_dir: Path
    shell_env: Callable[[], Awaitable[Mapping[str, str]]]
    account: Callable[[], Awaitable[RunAccount | None]]


async def chat_options(chat: NewChat) -> ClaudeAgentOptions:
    """A new General chat's options on Haiku, for one turn that keeps no transcript."""
    chat.folder.mkdir(parents=True, exist_ok=True)
    spec = SessionSpec(
        cwd=chat.folder,
        permission_mode=None,
        model=MODEL,
        system_prompt_append=chat.prompt,
        nest_tools=chat.tools,
        guard_git=False,
        account=await chat.account(),
        keep_history=False,
    )
    options = build_options(
        spec, NoTools(), chat.gh_config_dir, shell_env=dict(await chat.shell_env())
    )
    return dataclasses.replace(options, max_turns=1)


class ContextCost:
    def __init__(
        self,
        chat: NewChat,
        factory: ContextClientFactory,
        claude_md: tuple[Path, Path],
    ) -> None:
        """`claude_md` are the user's and General's CLAUDE.md, whose sizes are kept to
        name a cause in What changed."""
        self._chat = chat
        self._factory = factory
        self._claude_md = claude_md

    async def __call__(self) -> Collected:
        raw = await self._turn()
        return breakdown(
            raw,
            nest_prompt=_estimate(len(self._chat.prompt)),
            nest_tools=_estimate(sum(_tool_chars(tool) for tool in self._chat.tools)),
            claude_md=tuple(_size(path) for path in self._claude_md),
        )

    async def _turn(self) -> Mapping[str, object]:
        client = self._factory(await chat_options(self._chat))
        try:
            async with asyncio.timeout(TURN_SECONDS):
                await client.connect()
                await client.query(PROMPT)
                async for message in client.receive_messages():
                    if isinstance(message, ResultMessage):
                        break
                return cast("Mapping[str, object]", await client.get_context_usage())
        finally:
            await client.disconnect()


def breakdown(
    raw: Mapping[str, object],
    nest_prompt: int,
    nest_tools: int,
    claude_md: Sequence[int | None],
) -> Collected:
    """The section from Claude Code's context breakdown."""
    categories = _categories(raw)
    used = {name: tokens for name, tokens, deferred in categories if not deferred}
    deferred = sum(tokens for _, tokens, is_deferred in categories if is_deferred)
    reported = _number(raw.get("totalTokens"))
    # A new chat has no messages yet: the measuring turn's own are left out.
    total = None if reported is None else reported - used.get(_MESSAGES, 0)
    system_prompt = used.get(_SYSTEM_PROMPT, 0)
    loaded = used.get(_MCP_TOOLS, 0)
    # Nest's tools are an MCP server of the run: counted there unless tool search deferred them.
    nest_tools_used = nest_tools if loaded >= nest_tools else 0
    mcp = loaded - nest_tools_used + used.get(_MCP_INSTRUCTIONS, 0)
    parts = [
        ("system_prompt", "System prompt", max(0, system_prompt - nest_prompt)),
        ("tools", "Tools", used.get(_SYSTEM_TOOLS, 0)),
        ("mcp_tools", "MCP tools", mcp),
        ("memory", "Memory files", used.get(_MEMORY, 0)),
        ("skills", "Skills", used.get(_SKILLS, 0)),
        ("nest_prompt", "Nest instructions (estimate)", nest_prompt),
        ("nest_tools", "Nest tools (estimate)", nest_tools_used),
    ]
    limit = _number(raw.get("maxTokens"))
    deferred_nest = nest_tools > 0 and nest_tools_used == 0
    metrics = [
        Measured(
            id="total",
            label="New chat context",
            unit="tokens",
            better="lower",
            value=total,
            sub=None if limit is None else f"of {compact(limit)}",
            parts=[Part(label=label, value=value) for _, label, value in parts],
        ),
        Measured(
            id="share",
            label="Share of the context window",
            unit="percent",
            better="lower",
            value=None if total is None or not limit else total / limit * 100,
        ),
        *(
            Measured(
                id=key,
                label=label,
                unit="tokens",
                better="lower",
                value=value,
                sub="deferred by tool search" if key == "nest_tools" and deferred_nest else None,
            )
            for key, label, value in parts
        ),
        Measured(
            id="without_tool_search",
            label="Without tool search",
            unit="tokens",
            better="lower",
            value=None if total is None else total + deferred,
            sub="every MCP tool loaded",
        ),
    ]
    user_md, general_md = [*claude_md, None, None][:2]
    return Collected(
        metrics=metrics,
        facts={
            "mcp_servers": list[JsonValue](sorted(_mcp_servers(raw))),
            "skills": _skill_count(raw),
            "user_claude_md": user_md,
            "general_claude_md": general_md,
            "model": model if isinstance(model := raw.get("model"), str) else None,
        },
    )


def _categories(raw: Mapping[str, object]) -> list[tuple[str, float, bool]]:
    found: list[tuple[str, float, bool]] = []
    entries = raw.get("categories")
    for entry in cast("list[object]", entries) if isinstance(entries, list) else []:
        if not isinstance(entry, dict):
            continue
        item = cast("dict[str, object]", entry)
        name, tokens = item.get("name"), _number(item.get("tokens"))
        if isinstance(name, str) and tokens is not None and name != _FREE:
            found.append((name, tokens, item.get("isDeferred") is True))
    return found


def _mcp_servers(raw: Mapping[str, object]) -> set[str]:
    tools = raw.get("mcpTools")
    names: set[str] = set()
    for tool in cast("list[object]", tools) if isinstance(tools, list) else []:
        if isinstance(tool, dict):
            server = cast("dict[str, object]", tool).get("serverName")
            if isinstance(server, str):
                names.add(server)
    return names


def _skill_count(raw: Mapping[str, object]) -> int | None:
    skills = raw.get("skills")
    if not isinstance(skills, dict):
        return None
    count = cast("dict[str, object]", skills).get("totalSkills")
    return count if isinstance(count, int) else None


def _number(raw: object) -> float | None:
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        return None
    return float(raw)


def _estimate(chars: int) -> int:
    return round(chars / CHARS_PER_TOKEN)


def _tool_chars(tool: AgentTool) -> int:
    return len(tool.name) + len(tool.description) + len(json.dumps(tool.schema))


def _size(path: Path) -> int | None:
    try:
        return path.stat().st_size
    except OSError:
        return None
