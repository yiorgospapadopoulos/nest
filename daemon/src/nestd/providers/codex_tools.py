"""Nest's tools for a Codex run, served as a local MCP server (B91 stage 2).

Codex takes tools from MCP servers, so each Codex run that has Nest tools gets its own
streamable HTTP MCP server on 127.0.0.1 and an ephemeral port: the run's own tools under
`/pixie/mcp`, the tools every run has under `/nest/mcp`, as Claude's runs get them
in-process (`claude_tools`), built by the same code. Every request must carry the run's
random bearer token; the server and the token end with the run.

Codex learns the server from the thread's config overrides only (`config()`), never from
the user's `~/.codex/config.toml`. The token reaches Codex as an environment variable of the
app-server process (`env()`), named in the config by `bearer_token_env_var`, so it is in no
config, log, event or transcript. Codex's default shell environment policy leaves variables
named like `*TOKEN*` out of the commands it runs.
"""

import asyncio
import hmac
import secrets
import socket
from collections.abc import Mapping
from contextlib import AsyncExitStack, suppress
from typing import Any

import uvicorn
from claude_agent_sdk import create_sdk_mcp_server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import PlainTextResponse
from starlette.types import Receive, Scope, Send
from uvicorn.server import ServerState

from nestd.providers.base import AgentTool
from nestd.providers.claude_tools import to_sdk_tool
from nestd.providers.codex_rpc import JsonObject

TOKEN_ENV = "NEST_MCP_TOKEN"  # noqa: S105 (the variable's name, not a token)
HOST = "127.0.0.1"
# A call of a pixie waits for that pixie's chat to finish (B91), far past Codex's default.
TOOL_TIMEOUT_SECONDS = 86_400
# Nest's own tools check their callers themselves, so Codex never asks before one runs.
APPROVAL_MODE = "approve"
CLOSE_SECONDS = 5.0


class ToolHost:
    """One run's MCP server: `servers` maps a server name to its tools."""

    def __init__(self, servers: Mapping[str, tuple[AgentTool, ...]]) -> None:
        """Use `start`, which waits until it serves."""
        self.token = secrets.token_urlsafe(32)
        self._socket = socket.create_server((HOST, 0))
        self.port: int = self._socket.getsockname()[1]
        security = TransportSecuritySettings(
            enable_dns_rebinding_protection=True, allowed_hosts=[f"{HOST}:{self.port}"]
        )
        self._managers = {
            f"/{name}/mcp": StreamableHTTPSessionManager(
                create_sdk_mcp_server(name, tools=[to_sdk_tool(t) for t in tools])["instance"],
                json_response=True,
                stateless=True,
                security_settings=security,
            )
            for name, tools in servers.items()
        }
        self._names = tuple(servers)
        self._stop = asyncio.Event()
        self._ready = asyncio.get_running_loop().create_future()
        self._task = asyncio.create_task(self._serve())

    @classmethod
    async def start(cls, servers: Mapping[str, tuple[AgentTool, ...]]) -> "ToolHost":
        host = cls(servers)
        await asyncio.wait({host._ready, host._task}, return_when=asyncio.FIRST_COMPLETED)
        if not host._ready.done():
            await host._task  # it failed before serving: raise why
        return host

    def config(self) -> JsonObject:
        """The thread's config overrides that add the servers, as `-c key=value` would."""
        return {
            f"mcp_servers.{name}": {
                "url": f"http://{HOST}:{self.port}/{name}/mcp",
                "bearer_token_env_var": TOKEN_ENV,
                "default_tools_approval_mode": APPROVAL_MODE,
                "tool_timeout_sec": TOOL_TIMEOUT_SECONDS,
            }
            for name in self._names
        }

    def env(self) -> dict[str, str]:
        """What the app-server process needs to reach the servers: the token."""
        return {TOKEN_ENV: self.token}

    async def close(self) -> None:
        """Stop serving: tool calls still running are cancelled, the token is gone."""
        self._stop.set()
        await asyncio.gather(self._task, return_exceptions=True)

    async def _serve(self) -> None:
        try:
            await self._listen()
        finally:
            self._socket.close()

    async def _listen(self) -> None:
        loop = asyncio.get_running_loop()
        config = uvicorn.Config(
            self._app,
            interface="asgi3",
            lifespan="off",
            log_config=None,
            access_log=False,
            proxy_headers=False,
        )
        config.load()
        state = ServerState()

        def protocol() -> asyncio.Protocol:
            # One connection's HTTP handling, as uvicorn's own server makes it.
            made: Any = config.http_protocol_class(config=config, server_state=state, app_state={})  # pyright: ignore[reportCallIssue]
            return made

        async with AsyncExitStack() as running:
            for manager in self._managers.values():
                await running.enter_async_context(manager.run())
            server = await loop.create_server(protocol, sock=self._socket)
            self._ready.set_result(None)
            try:
                await self._stop.wait()
            finally:
                server.close()
        # The managers stopped above, which cancelled the calls in flight.
        for connection in list(state.connections):
            connection.shutdown()
        with suppress(TimeoutError):
            async with asyncio.timeout(CLOSE_SECONDS):
                await server.wait_closed()

    async def _app(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not self._authorized(scope):
            await PlainTextResponse("Unauthorized", status_code=401)(scope, receive, send)
            return
        manager = self._managers.get(str(scope.get("path", "")).rstrip("/"))
        if manager is None:
            await PlainTextResponse("Not found", status_code=404)(scope, receive, send)
            return
        await manager.handle_request(scope, receive, send)

    def _authorized(self, scope: Scope) -> bool:
        headers: list[tuple[bytes, bytes]] = scope.get("headers", [])
        value = next((v for k, v in headers if k.lower() == b"authorization"), b"")
        scheme, _, token = value.decode("latin-1").partition(" ")
        return scheme.lower() == "bearer" and hmac.compare_digest(
            token.encode(), self.token.encode()
        )
