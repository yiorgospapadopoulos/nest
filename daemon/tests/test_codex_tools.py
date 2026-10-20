"""Nest's tools served to a Codex run as a local MCP server (B91 stage 2)."""

import asyncio
import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import httpx
import httpx2
import pytest
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from pydantic import JsonValue

from nestd.providers.base import AgentTool, ToolRefusedError
from nestd.providers.codex_tools import TOKEN_ENV, ToolHost


def _tools(calls: list[dict[str, JsonValue]]) -> tuple[AgentTool, ...]:
    async def remember(args: dict[str, JsonValue]) -> str:
        calls.append(args)
        return f"saved {args['fact']}"

    async def forget(args: dict[str, JsonValue]) -> str:
        msg = "Nothing to forget."
        raise ToolRefusedError(msg)

    schema: dict[str, JsonValue] = {
        "type": "object",
        "properties": {"fact": {"type": "string"}},
        "required": ["fact"],
    }
    return (
        AgentTool("memory_write", "Save a fact.", schema, remember),
        AgentTool("memory_forget", "Forget a fact.", {"type": "object", "properties": {}}, forget),
    )


@asynccontextmanager
async def _client(url: str, token: str) -> AsyncGenerator[ClientSession]:
    headers = {"Authorization": f"Bearer {token}"}
    async with (
        httpx2.AsyncClient(headers=headers) as http,
        streamable_http_client(url, http_client=http) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        yield session


def _url(host: ToolHost, server: str) -> str:
    entry = host.config()[f"mcp_servers.{server}"]
    assert isinstance(entry, dict)
    url = entry["url"]
    assert isinstance(url, str)
    return url


async def test_a_runs_tools_are_listed_and_called_with_its_token() -> None:
    calls: list[dict[str, JsonValue]] = []
    host = await ToolHost.start({"pixie": _tools(calls)})
    try:
        async with _client(_url(host, "pixie"), host.token) as session:
            listed = await session.list_tools()
            saved = await session.call_tool("memory_write", {"fact": "tea"})
            refused = await session.call_tool("memory_forget", {})
    finally:
        await host.close()

    assert [tool.name for tool in listed.tools] == ["memory_write", "memory_forget"]
    assert listed.tools[0].description == "Save a fact."
    assert calls == [{"fact": "tea"}]
    assert not saved.is_error
    assert [part.model_dump()["text"] for part in saved.content] == ["saved tea"]
    assert refused.is_error
    assert [part.model_dump()["text"] for part in refused.content] == ["Nothing to forget."]


async def test_each_server_has_its_own_path_and_tools() -> None:
    nest_calls: list[dict[str, JsonValue]] = []

    async def create(args: dict[str, JsonValue]) -> str:
        nest_calls.append(args)
        return "created"

    nest = (
        AgentTool(
            "create_artifact",
            "Save an artifact.",
            {"type": "object", "properties": {"title": {"type": "string"}}},
            create,
        ),
    )
    host = await ToolHost.start({"pixie": _tools([]), "nest": nest})
    try:
        async with _client(_url(host, "nest"), host.token) as session:
            listed = await session.list_tools()
            await session.call_tool("create_artifact", {"title": "Plan"})
    finally:
        await host.close()

    assert [tool.name for tool in listed.tools] == ["create_artifact"]
    assert nest_calls == [{"title": "Plan"}]


@pytest.mark.parametrize(
    "authorization", [None, "Bearer wrong", "Basic abc", "Bearer", "bearer {token}x"]
)
async def test_a_request_without_the_runs_token_is_refused(authorization: str | None) -> None:
    host = await ToolHost.start({"pixie": _tools([])})
    headers = {"Accept": "application/json, text/event-stream"}
    if authorization is not None:
        headers["Authorization"] = authorization.format(token=host.token)
    try:
        async with httpx.AsyncClient() as http:
            response = await http.post(
                _url(host, "pixie"),
                headers=headers,
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
            )
    finally:
        await host.close()

    assert response.status_code == 401
    assert host.token not in response.text


async def test_an_unknown_path_is_not_found() -> None:
    host = await ToolHost.start({"pixie": _tools([])})
    url = _url(host, "pixie").replace("/pixie/", "/other/")
    try:
        async with httpx.AsyncClient() as http:
            response = await http.post(
                url, headers={"Authorization": f"Bearer {host.token}"}, json={}
            )
    finally:
        await host.close()

    assert response.status_code == 404


async def test_the_server_listens_on_localhost_only_and_stops_with_the_run() -> None:
    host = await ToolHost.start({"pixie": _tools([])})
    url = _url(host, "pixie")
    assert url == f"http://127.0.0.1:{host.port}/pixie/mcp"
    await host.close()
    await host.close()  # closing twice is harmless

    async with httpx.AsyncClient() as http:
        with pytest.raises(httpx.ConnectError):
            await http.post(url, headers={"Authorization": f"Bearer {host.token}"}, json={})


async def test_the_config_names_the_token_by_its_variable_never_its_value() -> None:
    host = await ToolHost.start({"pixie": _tools([]), "nest": _tools([])})
    try:
        config = host.config()
        other = await ToolHost.start({"pixie": _tools([])})
        await other.close()
    finally:
        await host.close()

    assert set(config) == {"mcp_servers.pixie", "mcp_servers.nest"}
    assert config["mcp_servers.pixie"] == {
        "url": f"http://127.0.0.1:{host.port}/pixie/mcp",
        "bearer_token_env_var": TOKEN_ENV,
        "default_tools_approval_mode": "approve",
        "tool_timeout_sec": 86400,
    }
    assert host.token not in json.dumps(config)
    assert host.env() == {TOKEN_ENV: host.token}
    # Each run has its own token, long and random.
    assert len(host.token) >= 40
    assert other.token != host.token


async def test_closing_cancels_a_call_still_running() -> None:
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def wait(args: dict[str, JsonValue]) -> str:
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise
        raise AssertionError  # pragma: no cover (never ends on its own)

    tools = (AgentTool("call_pixie", "Call.", {"type": "object", "properties": {}}, wait),)
    host = await ToolHost.start({"nest": tools})

    async def call() -> None:
        async with _client(_url(host, "nest"), host.token) as session:
            await session.call_tool("call_pixie", {})

    calling = asyncio.create_task(call())
    async with asyncio.timeout(5):
        await started.wait()
        await host.close()
        await cancelled.wait()
    calling.cancel()
    await asyncio.gather(calling, return_exceptions=True)


async def test_a_server_that_cannot_start_fails_the_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken(self: StreamableHTTPSessionManager) -> object:
        msg = "no task group"
        raise RuntimeError(msg)

    monkeypatch.setattr(StreamableHTTPSessionManager, "run", broken)

    with pytest.raises(RuntimeError, match="no task group"):
        await ToolHost.start({"nest": _tools([])})
