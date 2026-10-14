from pathlib import Path
from typing import Any, cast

from pydantic import JsonValue

from nestd.providers.base import AgentTool, ToolRefusedError
from nestd.providers.claude_tools import (
    TOOL_SERVER,
    own_tool_names,
    to_sdk_tool,
    tool_servers,
    write_guard,
)


async def echo(args: dict[str, JsonValue]) -> str:
    return f"got {args['text']}"


async def refuse(_args: dict[str, JsonValue]) -> str:
    raise ToolRefusedError("not allowed: autonomy is observe")


ECHO = AgentTool("echo", "Echo text", {"type": "object", "properties": {}}, echo)


async def test_tools_answer_with_text_and_refusals_as_errors() -> None:
    ok = await to_sdk_tool(ECHO).handler({"text": "hi"})
    refused = await to_sdk_tool(AgentTool("no", "No", {}, refuse)).handler({})

    assert ok == {"content": [{"type": "text", "text": "got hi"}]}
    assert refused == {
        "content": [{"type": "text", "text": "not allowed: autonomy is observe"}],
        "is_error": True,
    }


def test_tool_servers_and_own_tools() -> None:
    servers = tool_servers((ECHO,))

    assert tool_servers(()) == {}
    assert list(servers) == [TOOL_SERVER]
    assert servers[TOOL_SERVER].get("type") == "sdk"
    assert own_tool_names((ECHO,)) == {"mcp__pixie__echo"}
    assert own_tool_names(()) == frozenset()


async def guard(root: Path, tool: str, tool_input: dict[str, Any]) -> dict[str, Any]:
    hook = write_guard(root)
    data = {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input}
    return cast(dict[str, Any], await hook(cast(Any, data), None, cast(Any, {})))


async def test_the_write_guard_keeps_edits_inside_the_root(tmp_path: Path) -> None:
    root = tmp_path / "workdir"
    inside = await guard(root, "Write", {"file_path": str(root / "a.md")})
    relative = await guard(root, "Edit", {"file_path": "a.md"})
    outside = await guard(root, "Edit", {"file_path": str(tmp_path / "repo" / "x.py")})
    empty = await guard(root, "Write", {})
    root.mkdir()
    (root / "link").symlink_to(tmp_path / "repo")
    through_link = await guard(root, "Write", {"file_path": str(root / "link" / "x.py")})
    escape = await guard(root, "Write", {"file_path": str(root / ".." / "SOUL.md")})
    notebook = await guard(root, "NotebookEdit", {"notebook_path": "/etc/x.ipynb"})
    read = await guard(root, "Read", {"file_path": "/etc/hosts"})
    other_event = await write_guard(root)(
        cast(Any, {"hook_event_name": "PostToolUse"}), None, cast(Any, {})
    )

    assert inside == {}
    assert read == {}
    assert other_event == {}
    for denied in (relative, empty, through_link, outside, escape, notebook):
        assert denied["hookSpecificOutput"]["permissionDecision"] == "deny"
