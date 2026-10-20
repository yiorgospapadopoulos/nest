from pathlib import Path
from typing import Any, cast

from pydantic import JsonValue

from nestd.providers.base import AgentTool, CallRules, ToolRefusedError
from nestd.providers.claude_tools import (
    MEMBER_CALL_DENIED,
    NEST_SERVER,
    PIXIE_CALL_DENIED,
    TOOL_SERVER,
    call_guard,
    nest_tool_names,
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


def test_every_runs_tools_get_their_own_server() -> None:
    only_nest = tool_servers((), (ECHO,))
    both = tool_servers((ECHO,), (ECHO,))

    assert list(only_nest) == [NEST_SERVER] == ["nest"]
    assert list(both) == [TOOL_SERVER, NEST_SERVER]
    assert nest_tool_names((ECHO,)) == {"mcp__nest__echo"}
    assert nest_tool_names(()) == frozenset()


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


RULES = CallRules(
    pixies=frozenset({"lead", "bugs", "style", "solo"}),
    main=frozenset({"lead", "solo"}),
    leaders={"lead": frozenset({"bugs", "style"})},
)


async def call(
    tool_input: dict[str, Any], caller: str | None = None, tool: str = "Agent"
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "hook_event_name": "PreToolUse",
        "tool_name": tool,
        "tool_input": tool_input,
    }
    if caller is not None:
        data |= {"agent_id": "a-1", "agent_type": caller}
    return cast(dict[str, Any], await call_guard(RULES)(cast(Any, data), None, cast(Any, {})))


def denial(output: dict[str, Any]) -> str:
    specific = output["hookSpecificOutput"]
    assert specific["permissionDecision"] == "deny"
    return specific["permissionDecisionReason"]


async def test_the_main_agent_calls_solo_pixies_and_leaders_only() -> None:
    assert await call({"subagent_type": "solo", "prompt": "p"}) == {}
    assert await call({"subagent_type": "lead"}, tool="Task") == {}
    assert denial(await call({"subagent_type": "bugs"})) == MEMBER_CALL_DENIED.format(slug="bugs")
    assert MEMBER_CALL_DENIED.format(slug="bugs") == (
        "bugs is in a team and is called only by its leader. Hand the request to the team's"
        " leader instead; it calls its members."
    )


async def test_ordinary_subagents_are_never_touched() -> None:
    for caller in (None, "lead", "bugs", "Explore"):
        assert await call({"subagent_type": "Explore", "prompt": "p"}, caller) == {}
        assert await call({"prompt": "no type"}, caller) == {}
        assert await call({"subagent_type": 7}, caller) == {}
    assert await call(cast(Any, "not a dict")) == {}


async def test_only_a_leader_calls_pixies_and_only_its_own_members() -> None:
    for caller, target in (
        ("bugs", "style"),
        ("solo", "bugs"),
        ("Explore", "solo"),
        ("general-purpose", "lead"),
        ("lead", "solo"),
        ("lead", "lead"),
    ):
        assert denial(await call({"subagent_type": target}, caller)) == PIXIE_CALL_DENIED
    assert PIXIE_CALL_DENIED == (
        "Only a team's leader calls pixies, and only its own team's members. Use Claude"
        " Code's ordinary subagents (such as Explore or general-purpose) instead."
    )


async def test_a_subagent_without_a_type_calls_no_pixies() -> None:
    data = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Agent",
        "tool_input": {"subagent_type": "bugs"},
        "agent_id": "a-1",
    }

    output = await call_guard(RULES)(cast(Any, data), None, cast(Any, {}))

    assert denial(cast(dict[str, Any], output)) == PIXIE_CALL_DENIED


async def test_a_leader_waits_for_each_member_it_calls() -> None:
    waiting = {"subagent_type": "bugs", "prompt": "p", "run_in_background": False}

    assert await call(waiting, "lead") == {}
    for asked in ({"subagent_type": "bugs", "prompt": "p"}, {**waiting, "run_in_background": True}):
        # No permission decision: the call still goes through the usual permission checks.
        assert await call(asked, "lead") == {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "updatedInput": {**asked, "run_in_background": False},
            }
        }


CALL_TOOL = "mcp__nest__call_pixie"


async def test_nests_call_tool_is_guarded_like_the_agent_tool() -> None:
    # The main agent calls solo pixies and leaders; a leader its own members.
    assert await call({"pixie": "solo", "task": "t"}, tool=CALL_TOOL) == {}
    assert denial(await call({"pixie": "bugs", "task": "t"}, tool=CALL_TOOL)) == (
        MEMBER_CALL_DENIED.format(slug="bugs")
    )
    assert await call({"pixie": "bugs", "task": "t"}, "lead", tool=CALL_TOOL) == {}
    assert denial(await call({"pixie": "solo", "task": "t"}, "bugs", tool=CALL_TOOL)) == (
        PIXIE_CALL_DENIED
    )
    # Its input never names a subagent, and it waits for its report anyway.
    assert await call({"subagent_type": "bugs"}, tool=CALL_TOOL) == {}
