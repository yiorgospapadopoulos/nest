"""MCP servers in each engine's shape, and turning one into the other (contract rule 6).

Nest's shape is Claude's (`.claude.json` and `.mcp.json` `mcpServers`). Codex keeps
`[mcp_servers.<name>]` tables: stdio `command/args/env`, http `url` with
`bearer_token_env_var` and `http_headers`. Codex has no SSE and does not expand `${VAR}`,
so a server needing either stays with Claude.
"""

import json
import re
from pathlib import Path
from typing import Literal, Self, cast

from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError, model_validator

from nestd.configuration.files import read_text, write_text
from nestd.errors import InvalidInputError

type Transport = Literal["stdio", "http", "sse"]
type JsonObject = dict[str, JsonValue]
SERVERS_KEY = "mcpServers"
NAME_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"
_BEARER = re.compile(r"^Bearer \$\{([A-Za-z_][A-Za-z0-9_]*)\}$")
_VARIABLE = "${"
NO_SSE = "Codex has no SSE servers"
VARIABLES = "Uses ${...} variables, which Codex does not fill in"
APP_PATH = "Uses a path inside the Codex app"


class McpServer(BaseModel):
    """A server as Claude keeps it; also the body of `PUT .../mcp-servers/{name}`."""

    model_config = ConfigDict(extra="forbid")

    transport: Transport
    command: str | None = None
    args: list[str] = Field(default_factory=list[str])
    env: dict[str, str] = Field(default_factory=dict[str, str])
    url: str | None = None
    headers: dict[str, str] = Field(default_factory=dict[str, str])

    @model_validator(mode="after")
    def _complete(self) -> Self:
        if self.transport == "stdio" and not self.command:
            msg = "a stdio server needs a command"
            raise ValueError(msg)
        if self.transport != "stdio" and not self.url:
            msg = f"an {self.transport} server needs a url"
            raise ValueError(msg)
        return self

    def summary(self) -> str:
        if self.transport == "stdio":
            return " ".join([cast("str", self.command), *self.args])
        return cast("str", self.url)


class McpServerSummary(BaseModel):
    name: str
    summary: str
    transport: Transport


def from_claude(entry: JsonValue) -> McpServer | None:
    """A `mcpServers` entry; None when it is not one Nest understands."""
    if not isinstance(entry, dict):
        return None
    kind = entry.get("type") or ("stdio" if "command" in entry else None)
    fields = {key: entry.get(key) for key in ("command", "args", "env", "url", "headers")}
    try:
        return McpServer.model_validate(
            {"transport": kind, **{k: v for k, v in fields.items() if v is not None}}
        )
    except ValidationError:
        return None


def to_claude(server: McpServer) -> JsonObject:
    if server.transport == "stdio":
        return {
            "type": "stdio",
            "command": server.command,
            "args": list(server.args),
            "env": dict(server.env),
        }
    entry: JsonObject = {"type": server.transport, "url": server.url}
    if server.headers:
        entry["headers"] = dict(server.headers)
    return entry


def to_codex(server: McpServer) -> tuple[JsonObject | None, str | None]:
    """The Codex table, or None and why it cannot be one."""
    if server.transport == "sse":
        return None, NO_SSE
    if server.transport == "stdio":
        values = [server.command or "", *server.args, *server.env.values()]
        if any(_VARIABLE in value for value in values):
            return None, VARIABLES
        table: JsonObject = {"command": server.command}
        if server.args:
            table["args"] = list(server.args)
        if server.env:
            table["env"] = dict(server.env)
        return table, None
    table = {"url": server.url}
    headers: dict[str, JsonValue] = {}
    for key, value in server.headers.items():
        bearer = _BEARER.match(value) if key.lower() == "authorization" else None
        if bearer is not None:
            table["bearer_token_env_var"] = bearer[1]
        elif _VARIABLE in value:
            return None, VARIABLES
        else:
            headers[key] = value
    if _VARIABLE in (server.url or ""):
        return None, VARIABLES
    if headers:
        table["http_headers"] = headers
    return table, None


def claude_problem(server: McpServer) -> str | None:
    """Why Claude cannot run a server Codex has: a command path relative to Codex's own
    folder, such as the ChatGPT app's bundled servers.
    """
    command = server.command or ""
    if server.transport == "stdio" and "/" in command and not command.startswith("/"):
        return APP_PATH
    return None


def from_codex(table: JsonValue) -> McpServer | None:
    """A Codex `[mcp_servers.<name>]` table in Claude's shape; None when it has neither a
    url nor a command.
    """
    if not isinstance(table, dict):
        return None
    try:
        if isinstance(table.get("url"), str):
            headers = _strings(table.get("http_headers"))
            variable = table.get("bearer_token_env_var")
            if isinstance(variable, str):
                headers["Authorization"] = f"Bearer ${{{variable}}}"
            return McpServer(transport="http", url=cast("str", table["url"]), headers=headers)
        return McpServer(
            transport="stdio",
            command=cast("str | None", table.get("command")),
            args=[arg for arg in _list(table.get("args")) if isinstance(arg, str)],
            env=_strings(table.get("env")),
        )
    except ValidationError:
        return None


def _strings(value: JsonValue) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {key: item for key, item in value.items() if isinstance(item, str)}


def _list(value: JsonValue) -> list[JsonValue]:
    return value if isinstance(value, list) else []


class ServersFile:
    """The `mcpServers` of a JSON file (`.claude.json` or a repo's `.mcp.json`), changed by
    key: every other key stays, in its order.
    """

    def __init__(self, path: Path) -> None:
        self.path = path

    def servers(self) -> dict[str, McpServer]:
        entries = self._read().get(SERVERS_KEY)
        if not isinstance(entries, dict):
            return {}
        found = {name: from_claude(entry) for name, entry in entries.items()}
        return {name: server for name, server in found.items() if server is not None}

    def put(self, name: str, server: McpServer) -> None:
        data = self._read()
        entries = data.get(SERVERS_KEY)
        entries = entries if isinstance(entries, dict) else {}
        entries[name] = to_claude(server)
        data[SERVERS_KEY] = entries
        self._write(data)

    def remove(self, name: str) -> bool:
        """False when it has no server by that name."""
        data = self._read()
        entries = data.get(SERVERS_KEY)
        if not isinstance(entries, dict) or name not in entries:
            return False
        del entries[name]
        self._write(data)
        return True

    def _read(self) -> JsonObject:
        text = read_text(self.path)
        if not text.strip():
            return {}
        try:
            data: JsonValue = json.loads(text)
        except ValueError as error:
            msg = f"{self.path} is not valid JSON"
            raise InvalidInputError(msg) from error
        if not isinstance(data, dict):
            msg = f"{self.path} is not a JSON object"
            raise InvalidInputError(msg)
        return data

    def _write(self, data: JsonObject) -> None:
        write_text(self.path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
