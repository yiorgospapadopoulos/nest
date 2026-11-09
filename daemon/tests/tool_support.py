"""Calling a Nest tool in a test."""

from pydantic import JsonValue

from nestd.providers.base import AgentTool


async def tool_text(tool: AgentTool, args: dict[str, JsonValue]) -> str:
    """The answer of a tool that answers in words only, not with pictures (B150)."""
    result = await tool.handler(args)
    assert isinstance(result, str)
    return result
