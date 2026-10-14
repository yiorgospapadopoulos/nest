"""Harness tools as an in-process MCP server, and the write guard for pixie runs (D072)."""

import asyncio
from pathlib import Path
from typing import Any

from claude_agent_sdk import McpServerConfig, SdkMcpTool, create_sdk_mcp_server
from claude_agent_sdk.types import HookCallback, HookContext, HookInput, HookJSONOutput

from harness.providers.base import AgentTool, ToolRefusedError

TOOL_SERVER = "pixie"
WRITE_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
WRITE_DENIED = "A pixie may only write files in its own workdir; use its memory tools instead."
SUBAGENT_DENIED = "A pixie's own tools are only for the pixie, not for agents it calls."


def own_tool_names(tools: tuple[AgentTool, ...]) -> frozenset[str]:
    """Claude Code's names for a run's own tools. They check their callers themselves, so
    they never prompt; a same-named server the user configured is not among them."""
    return frozenset(f"mcp__{TOOL_SERVER}__{tool.name}" for tool in tools)


def to_sdk_tool(tool: AgentTool) -> SdkMcpTool[Any]:
    async def handler(args: dict[str, Any]) -> dict[str, Any]:
        try:
            text = await tool.handler(args)
        except ToolRefusedError as error:
            return {"content": [{"type": "text", "text": str(error)}], "is_error": True}
        return {"content": [{"type": "text", "text": text}]}

    return SdkMcpTool(tool.name, tool.description, tool.schema, handler)


def tool_servers(tools: tuple[AgentTool, ...]) -> dict[str, McpServerConfig]:
    if not tools:
        return {}
    return {TOOL_SERVER: create_sdk_mcp_server(TOOL_SERVER, tools=[to_sdk_tool(t) for t in tools])}


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
