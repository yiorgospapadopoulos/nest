"""Harness tools as an in-process MCP server, and the write guard for pixie runs (D057)."""

from pathlib import Path
from typing import Any

from claude_agent_sdk import McpServerConfig, SdkMcpTool, create_sdk_mcp_server
from claude_agent_sdk.types import HookCallback, HookContext, HookInput, HookJSONOutput

from harness.providers.base import AgentTool, ToolRefusedError

TOOL_SERVER = "pixie"
WRITE_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
WRITE_DENIED = "A pixie may only write files in its own workdir; use its memory tools instead."


def own_tool(tool_name: str) -> bool:
    """Harness's own tools check their callers themselves, so they never prompt."""
    return tool_name.startswith(f"mcp__{TOOL_SERVER}__")


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
        target = (resolved_root / str(raw)).resolve()
        if target == resolved_root or resolved_root in target.parents:
            return {}
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": WRITE_DENIED,
            }
        }

    return guard
