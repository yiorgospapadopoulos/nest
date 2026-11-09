"""The `nest` command's entry point (B151). `nest mcp` started inside one of Nest's own
chats, which happens in every chat on an engine whose config has `nest-app`, answers here
with no tools and nothing heavy loaded; everything else goes to the full command."""

import json
import os
import socket
import sys
from pathlib import Path
from typing import cast

from nestd.paths import AppPaths
from nestd.platform import current_platform

ASK_SECONDS = 5.0


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    kind = _mcp_client(args)
    if kind is not None and _inside_nest(kind):
        serve_nothing()
        return 0
    from nestd.doctor.command import main as full

    return full(args)


def _mcp_client(args: list[str]) -> str | None:
    if len(args) == 3 and args[0] == "mcp" and args[1] == "--client":
        return args[2]
    return None


def _inside_nest(kind: str) -> bool:
    """Whether the daemon refuses this process as one of its own; anything else, a daemon
    that is down included, is the full server's to handle."""
    path = AppPaths.from_env(os.environ, Path.home(), current_platform()).outside_socket
    if path is None:
        return False
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(ASK_SECONDS)
            sock.connect(str(path))
            sock.sendall(kind.encode() + b"\n")
            sock.shutdown(socket.SHUT_WR)
            data = b"".join(iter(lambda: sock.recv(4096), b""))
        answer = _object(json.loads(data))
    except (OSError, ValueError):
        return False
    return answer is not None and answer.get("error") == "inside_nest"


def serve_nothing() -> None:
    """A minimal MCP server over standard input and output that offers no tools."""
    for line in sys.stdin:
        try:
            message = _object(json.loads(line))
        except ValueError:
            continue
        if message is None or "id" not in message:
            continue  # a notification
        reply = reply_to(message)
        sys.stdout.write(json.dumps(reply) + "\n")
        sys.stdout.flush()


def reply_to(message: dict[str, object]) -> dict[str, object]:
    method = message.get("method")
    reply: dict[str, object] = {"jsonrpc": "2.0", "id": message["id"]}
    if method == "initialize":
        params = _object(message.get("params"))
        version = None if params is None else params.get("protocolVersion")
        reply["result"] = {
            "protocolVersion": version if isinstance(version, str) else "2025-06-18",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "nest-app", "version": "1"},
            "instructions": "Inside Nest: use your Nest tools instead.",
        }
    elif method == "tools/list":
        reply["result"] = {"tools": []}
    elif method == "ping":
        reply["result"] = {}
    else:
        reply["error"] = {"code": -32601, "message": f"{method} is not offered inside Nest"}
    return reply


def _object(value: object) -> dict[str, object] | None:
    return cast("dict[str, object]", value) if isinstance(value, dict) else None
