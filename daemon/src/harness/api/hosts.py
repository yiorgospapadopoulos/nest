"""Host header check (H-02): a web page on another name cannot reach the API by DNS
rebinding. Requests must name this Mac: 127.0.0.1, localhost, [::1] (the Mac app), any
*.ts.net name (the iPhone through `tailscale serve`, which keeps the tailnet name), or a
name from `[server] allowed_hosts`. Event sockets are checked too.
"""

from collections.abc import Callable, Sequence

from starlette.datastructures import Headers
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

BUILT_IN_HOSTS = ("127.0.0.1", "localhost", "[::1]", "*.ts.net")
# Policy violation: a socket refused before it is accepted reaches the client as a 403.
REFUSED_SOCKET_CLOSE_CODE = 1008


class HostCheckMiddleware:
    def __init__(self, app: ASGIApp, allowed: Callable[[], Sequence[str]]) -> None:
        self._app = app
        # Read per request, so a reloaded settings file applies at once.
        self._allowed = allowed

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket") and not host_allowed(
            Headers(scope=scope).get("host"), self._allowed()
        ):
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": REFUSED_SOCKET_CLOSE_CODE})
            else:
                await PlainTextResponse("Invalid host header", status_code=400)(
                    scope, receive, send
                )
            return
        await self._app(scope, receive, send)


def host_allowed(host: str | None, extra: Sequence[str]) -> bool:
    """Whether a Host header names this Mac; `extra` holds names or *.domain patterns."""
    name = _host_name(host or "")
    return bool(name) and any(_matches(name, pattern) for pattern in (*BUILT_IN_HOSTS, *extra))


def _host_name(host: str) -> str:
    """The lowercase name without port or trailing dot; IPv6 keeps its brackets."""
    host = host.strip().lower()
    if host.startswith("["):
        end = host.find("]")
        return "" if end == -1 else host[: end + 1]
    return host.partition(":")[0].rstrip(".")


def _matches(name: str, pattern: str) -> bool:
    if pattern.startswith("*."):
        return name.endswith(pattern[1:])
    return name == pattern
