"""A Codex run's Nest tools, MCP approvals and write root (B91 stage 2)."""

import json
from pathlib import Path
from typing import cast

import httpx
import pytest
from pydantic import JsonValue

from nestd.providers.base import AgentTool, UserInput
from nestd.providers.codex_rpc import JsonObject
from nestd.providers.codex_tools import TOKEN_ENV, ToolHost
from tests.async_support import until
from tests.codex_support import FakeAppServer, item
from tests.recording_sink import RecordingSink
from tests.test_codex_provider import Handler, opened, provider, spec

SCHEMA: dict[str, JsonValue] = {"type": "object", "properties": {"fact": {"type": "string"}}}


def _tool(name: str, calls: list[str]) -> AgentTool:
    async def handler(args: dict[str, JsonValue]) -> str:
        calls.append(f"{name}:{args.get('fact')}")
        return f"{name} done"

    return AgentTool(name, f"The {name} tool.", SCHEMA, handler)


def _server(config: JsonObject, name: str) -> JsonObject:
    entry = config[f"mcp_servers.{name}"]
    assert isinstance(entry, dict)
    return entry


async def _call(url: str, token: str, tool: str) -> httpx.Response:
    async with httpx.AsyncClient() as http:
        return await http.post(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json, text/event-stream",
                "MCP-Protocol-Version": "2025-06-18",
            },
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": tool, "arguments": {"fact": "tea"}},
            },
        )


async def test_a_runs_nest_tools_are_served_to_its_thread_while_it_is_open(
    tmp_path: Path,
) -> None:
    calls: list[str] = []
    server, run, _, _ = await opened(
        tmp_path,
        tools=(_tool("memory_write", calls),),
        nest_tools=(_tool("create_artifact", calls),),
    )

    [start] = server.requests("thread/start")
    config = cast("JsonObject", start["config"])
    pixie = _server(config, "pixie")
    nest = _server(config, "nest")
    assert pixie["bearer_token_env_var"] == TOKEN_ENV
    token = server.launches[0].env[TOKEN_ENV]
    # The token is in the app-server's environment only, never in what Nest sends.
    assert token not in json.dumps(server.sent)
    called = await _call(str(nest["url"]), token, "create_artifact")
    assert called.status_code == 200
    assert calls == ["create_artifact:tea"]

    await run.close()
    with pytest.raises(httpx.ConnectError):
        await _call(str(pixie["url"]), token, "memory_write")


async def test_the_developer_instructions_name_the_runs_nest_tools(tmp_path: Path) -> None:
    """So the model finds them among the user's many MCP tools (B91 live check)."""
    server, run, _, _ = await opened(
        tmp_path,
        system_prompt_append="You are Coder.",
        tools=(_tool("memory_read", []), _tool("memory_write", [])),
        nest_tools=(_tool("create_artifact", []),),
    )

    [start] = server.requests("thread/start")
    assert start["developerInstructions"] == (
        "You are Coder.\n\n"
        "Nest's tools for this chat are MCP tools: mcp__pixie__memory_read,"
        " mcp__pixie__memory_write (the pixie server) and mcp__nest__create_artifact"
        " (the nest server)."
    )
    await run.close()


async def test_a_chat_with_only_nest_actions_is_told_of_them_alone(tmp_path: Path) -> None:
    server, run, _, _ = await opened(tmp_path, nest_tools=(_tool("call_pixie", []),))

    [start] = server.requests("thread/start")
    assert start["developerInstructions"] == (
        "Nest's tools for this chat are MCP tools: mcp__nest__call_pixie (the nest server)."
    )
    await run.close()


async def test_a_run_without_nest_tools_gets_no_server(tmp_path: Path) -> None:
    server, run, _, _ = await opened(tmp_path)

    [start] = server.requests("thread/start")
    assert start["config"] == {}
    assert "developerInstructions" not in start
    assert TOKEN_ENV not in server.launches[0].env
    await run.close()


async def test_a_run_that_fails_to_open_stops_its_tool_server(tmp_path: Path) -> None:
    server = FakeAppServer()
    server.answers["thread/start"] = {"thread": {}}
    nest = (_tool("create_artifact", []),)

    with pytest.raises(RuntimeError, match="no thread"):
        await provider(tmp_path, server).open(
            spec(tmp_path, nest_tools=nest), Handler(), RecordingSink()
        )

    [start] = server.requests("thread/start")
    url = str(_server(cast("JsonObject", start["config"]), "nest")["url"])
    with pytest.raises(httpx.ConnectError):
        await _call(url, server.launches[0].env[TOKEN_ENV], "create_artifact")


async def test_nests_own_tool_calls_are_accepted_and_other_servers_asked(
    tmp_path: Path,
) -> None:
    server, run, _, handler = await opened(tmp_path, nest_tools=(_tool("create_artifact", []),))
    meta: JsonObject = {"codex_approval_kind": "mcp_tool_call", "tool_params": {"repo": "a/b"}}
    call: JsonObject = {
        "type": "mcpToolCall",
        "id": "m1",
        "server": "github",
        "tool": "list_issues",
    }
    server.notify("item/started", item("started", call)["params"])  # type: ignore[arg-type]

    own = await server.request(
        "mcpServer/elicitation/request",
        {"serverName": "nest", "turnId": "turn-1", "mode": "form", "_meta": meta},
    )
    other = await server.request(
        "mcpServer/elicitation/request",
        {"serverName": "github", "turnId": "turn-1", "mode": "form", "_meta": meta},
    )

    assert own["result"] == other["result"] == {"action": "accept", "content": {}, "_meta": None}
    # The tool's name comes from the call Codex started before it asked.
    assert [r.tool_name for r in handler.requests] == ["mcp__github__list_issues"]
    assert handler.requests[0].tool_input == {"repo": "a/b"}
    await run.close()


def _user_config(server: FakeAppServer) -> None:
    server.answers["config/read"] = {
        "config": {
            "model": None,
            "mcp_servers": {
                "github": {"url": "https://api.example/mcp", "bearer_token_env_var": "GH_PAT"},
                "serena": {
                    "command": "serena",
                    "tools": {
                        "execute_shell_command": {"approval_mode": "approve"},
                        "odd.tool": {"approval_mode": "approve"},
                    },
                },
                "nest": {"command": "their-own-nest"},
                "bad name": {"command": "x"},
            },
        },
        "origins": {},
        "layers": None,
    }


async def test_a_guarded_run_makes_codex_ask_before_the_users_mcp_tools(
    tmp_path: Path,
) -> None:
    server = FakeAppServer()
    _user_config(server)
    run = await provider(tmp_path, server).open(
        spec(tmp_path, guard_git=True, nest_tools=(_tool("create_artifact", []),)),
        Handler(),
        RecordingSink(),
    )

    assert server.requests("config/read") == [{"cwd": str(tmp_path)}]
    [start] = server.requests("thread/start")
    config = cast("JsonObject", start["config"])
    assert config["mcp_servers.github.default_tools_approval_mode"] == "prompt"
    assert config["mcp_servers.serena.default_tools_approval_mode"] == "prompt"
    assert config["mcp_servers.serena.tools.execute_shell_command.approval_mode"] == "prompt"
    # Nest's own server replaces a same-named one; a name Codex would refuse is left alone.
    assert "mcp_servers.nest.default_tools_approval_mode" not in config
    assert not any("bad name" in key or "odd.tool" in key for key in config)
    await run.close()


async def test_a_normal_run_leaves_the_users_mcp_approvals_alone(tmp_path: Path) -> None:
    server = FakeAppServer()
    _user_config(server)
    run = await provider(tmp_path, server).open(spec(tmp_path), Handler(), RecordingSink())

    assert server.requests("config/read") == []
    await run.close()


async def test_a_pixie_runs_writes_stay_in_its_write_root(tmp_path: Path) -> None:
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    repo = tmp_path / "repo"
    server, run, _, _ = await opened(
        workdir,
        cwd=workdir,
        guard_git=True,
        permission_mode="bypassPermissions",
        write_root=workdir,
        extra_dirs=(repo,),
    )
    change = {"type": "fileChange", "id": "f1", "changes": [{"path": str(repo / "a.py")}]}
    server.notify("item/started", item("started", change)["params"])  # type: ignore[arg-type]

    await run.send(UserInput("hi"))
    [turn] = server.requests("turn/start")
    sandbox = cast("JsonObject", turn["sandboxPolicy"])
    assert sandbox["type"] == "workspaceWrite"
    # The projects are readable, not writable: only its workdir is.
    assert sandbox["writableRoots"] == []
    answer = await server.request("item/fileChange/requestApproval", {"itemId": "f1"})
    assert answer["result"] == {"decision": "decline"}
    await run.close()


async def test_codex_ending_on_its_own_stops_the_runs_tool_server(tmp_path: Path) -> None:
    server, run, sink, _ = await opened(tmp_path, nest_tools=(_tool("create_artifact", []),))
    [start] = server.requests("thread/start")
    url = str(_server(cast("JsonObject", start["config"]), "nest")["url"])

    server.transport.end()

    await until(lambda: any(kind == "stopped" for kind, _ in sink.calls))
    with pytest.raises(httpx.ConnectError):
        await _call(url, server.launches[0].env[TOKEN_ENV], "create_artifact")
    await run.close()


async def test_a_codex_that_cannot_start_stops_the_runs_tool_server(tmp_path: Path) -> None:
    server = FakeAppServer()
    server.spawn_error = OSError("no codex")
    started: list[ToolHost] = []
    real_start = ToolHost.start

    async def start(servers: dict[str, tuple[AgentTool, ...]]) -> ToolHost:
        started.append(await real_start(servers))
        return started[-1]

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(ToolHost, "start", start)
        with pytest.raises(OSError, match="no codex"):
            await provider(tmp_path, server).open(
                spec(tmp_path, nest_tools=(_tool("create_artifact", []),)),
                Handler(),
                RecordingSink(),
            )

    [host] = started
    with pytest.raises(httpx.ConnectError):
        await _call(f"http://127.0.0.1:{host.port}/nest/mcp", host.token, "create_artifact")


async def test_a_codex_that_cannot_start_without_tools_fails_the_open(tmp_path: Path) -> None:
    server = FakeAppServer()
    server.spawn_error = OSError("no codex")

    with pytest.raises(OSError, match="no codex"):
        await provider(tmp_path, server).open(spec(tmp_path), Handler(), RecordingSink())
