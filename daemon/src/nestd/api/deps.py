"""Request dependencies: the shared context and device authentication."""

from typing import Annotated

from fastapi import Depends, HTTPException, status
from starlette.requests import HTTPConnection

from nestd.auth.models import Device
from nestd.context import AppContext

COOKIE_NAME = "nest_token"
# A browser cannot set headers on a WebSocket, so the desktop app (B117) offers the
# subprotocols "nest" and "nest.token.<token>"; only "nest" is accepted back.
NEST_SUBPROTOCOL = "nest"
TOKEN_SUBPROTOCOL_PREFIX = "nest.token."  # noqa: S105 (a prefix, not a secret)
# Set at pairing before the rename to Nest (B43); still accepted until it expires.
LEGACY_COOKIE_NAME = "harness_token"


def get_context(conn: HTTPConnection) -> AppContext:
    ctx: AppContext = conn.app.state.ctx
    return ctx


Context = Annotated[AppContext, Depends(get_context)]


def _subprotocol_token(conn: HTTPConnection) -> str | None:
    """The token a WebSocket offered as a subprotocol, only next to "nest"."""
    offered: list[str] = conn.scope.get("subprotocols", [])
    if conn.scope["type"] != "websocket" or NEST_SUBPROTOCOL not in offered:
        return None
    for protocol in offered:
        if protocol.startswith(TOKEN_SUBPROTOCOL_PREFIX):
            return protocol.removeprefix(TOKEN_SUBPROTOCOL_PREFIX)
    return None


async def authenticated_device(conn: HTTPConnection, ctx: AppContext) -> Device | None:
    """Authenticate with `Authorization: Bearer <token>`, a WebSocket's token subprotocol,
    or the `nest_token` cookie (or the `harness_token` one from before the rename)."""
    scheme, _, credentials = conn.headers.get("authorization", "").partition(" ")
    token = (
        credentials.strip()
        if scheme.lower() == "bearer"
        else _subprotocol_token(conn)
        or conn.cookies.get(COOKIE_NAME)
        or conn.cookies.get(LEGACY_COOKIE_NAME)
    )
    if not token:
        return None
    return await ctx.devices.authenticate(token)


async def require_device(conn: HTTPConnection, ctx: Context) -> Device:
    device = await authenticated_device(conn, ctx)
    if device is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return device


RequireDevice = Depends(require_device)
