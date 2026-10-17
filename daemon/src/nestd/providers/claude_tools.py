"""Nest tools as an in-process MCP server, the write guard for pixie runs (D072), and the
guard of who calls which pixie (B70).
"""

import asyncio
from pathlib import Path
from typing import Any, cast

from claude_agent_sdk import McpServerConfig, SdkMcpTool, create_sdk_mcp_server
from claude_agent_sdk.types import HookCallback, HookContext, HookInput, HookJSONOutput

from nestd.providers.base import AgentTool, CallRules, ToolRefusedError

TOOL_SERVER = "pixie"
# The server of the tools every run gets (B79), so a chat shows `mcp__nest__create_artifact`.
NEST_SERVER = "nest"
WRITE_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
WRITE_DENIED = "A pixie may only write files in its own workdir; use its memory tools instead."
SUBAGENT_DENIED = "A pixie's own tools are only for the pixie, not for agents it calls."
MEMBER_CALL_DENIED = (
    "{slug} is in a team and is called only by its leader. Hand the request to the team's"
    " leader instead; it calls its members."
)
PIXIE_CALL_DENIED = (
    "Only a team's leader calls pixies, and only its own team's members. Use Claude Code's"
    " ordinary subagents (such as Explore or general-purpose) instead."
)


def own_tool_names(tools: tuple[AgentTool, ...]) -> frozenset[str]:
    """Claude Code's names for a run's own tools. They check their callers themselves, so
    they never prompt; a same-named server the user configured is not among them."""
    return frozenset(f"mcp__{TOOL_SERVER}__{tool.name}" for tool in tools)


def nest_tool_names(tools: tuple[AgentTool, ...]) -> frozenset[str]:
    """Claude Code's names for the tools every run gets (B79); they never prompt either."""
    return frozenset(f"mcp__{NEST_SERVER}__{tool.name}" for tool in tools)


def to_sdk_tool(tool: AgentTool) -> SdkMcpTool[Any]:
    async def handler(args: dict[str, Any]) -> dict[str, Any]:
        try:
            text = await tool.handler(args)
        except ToolRefusedError as error:
            return {"content": [{"type": "text", "text": str(error)}], "is_error": True}
        return {"content": [{"type": "text", "text": text}]}

    return SdkMcpTool(tool.name, tool.description, tool.schema, handler)


def tool_servers(
    tools: tuple[AgentTool, ...], nest_tools: tuple[AgentTool, ...] = ()
) -> dict[str, McpServerConfig]:
    """The in-process servers of a run's own tools and of every run's tools. Claude Code
    adds them to the user's own MCP servers (no strict MCP config), which stay as they are.
    """
    servers: dict[str, McpServerConfig] = {}
    for name, served in ((TOOL_SERVER, tools), (NEST_SERVER, nest_tools)):
        if served:
            servers[name] = create_sdk_mcp_server(name, tools=[to_sdk_tool(t) for t in served])
    return servers


def _deny(reason: str) -> HookJSONOutput:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def subagent_guard(own_tools: frozenset[str]) -> HookCallback:
    """PreToolUse hook that denies the run's own tools to its subagents in every mode: a
    pixie called inside a pixie's chat must not act with that pixie's tools (B41).
    """

    async def guard(
        input_data: HookInput, tool_use_id: str | None, context: HookContext
    ) -> HookJSONOutput:
        data: dict[str, Any] = dict(input_data)
        if data.get("tool_name") in own_tools and data.get("agent_id"):
            return _deny(SUBAGENT_DENIED)
        return {}

    return guard


def call_guard(rules: CallRules) -> HookCallback:
    """PreToolUse hook for the Agent tools: a pixie is called only as `rules` allow, and a
    leader waits for each member it calls. Calls of ordinary subagents are never touched.
    """

    async def guard(
        input_data: HookInput, tool_use_id: str | None, context: HookContext
    ) -> HookJSONOutput:
        data: dict[str, Any] = dict(input_data)
        raw = data.get("tool_input")
        tool_input = cast("dict[str, Any]", raw) if isinstance(raw, dict) else {}
        target = tool_input.get("subagent_type")
        if not isinstance(target, str) or target not in rules.pixies:
            return {}
        # The main agent has no agent id; a subagent's type is the name it was called by.
        caller = str(data.get("agent_type") or "") if data.get("agent_id") else None
        if not rules.may_call(caller, target):
            return _deny(
                PIXIE_CALL_DENIED if caller is not None else MEMBER_CALL_DENIED.format(slug=target)
            )
        if caller is None or tool_input.get("run_in_background") is False:
            return {}
        # Inside a subagent an Agent call runs in the background unless told not to. With
        # no permission decision the changed call still goes through the usual checks.
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "updatedInput": {**tool_input, "run_in_background": False},
            }
        }

    return guard


def write_guard(root: Path) -> HookCallback:
    """PreToolUse hook that denies file edits outside `root`, in every permission mode."""
    resolved_root = root.resolve()

    async def guard(
        input_data: HookInput, tool_use_id: str | None, context: HookContext
    ) -> HookJSONOutput:
        if input_data["hook_event_name"] != "PreToolUse":
            return {}
        if input_data["tool_name"] not in WRITE_TOOLS:
            return {}
        tool_input = input_data["tool_input"]
        raw = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
        # Claude Code resolves a relative path against the run's cwd, not the root, so
        # only an absolute path can be judged here; anything else is denied.
        path = Path(str(raw))
        if path.is_absolute():
            target = await asyncio.to_thread(path.resolve)
            if target == resolved_root or resolved_root in target.parents:
                return {}
        return _deny(WRITE_DENIED)

    return guard
