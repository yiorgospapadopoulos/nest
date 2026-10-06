"""Request dependencies: the shared context and device authentication."""

from typing import Annotated

from fastapi import Depends, HTTPException, status
from starlette.requests import HTTPConnection

from harness.auth.models import Device
from harness.context import AppContext

COOKIE_NAME = "harness_token"


def get_context(conn: HTTPConnection) -> AppContext:
    ctx: AppContext = conn.app.state.ctx
    return ctx


Context = Annotated[AppContext, Depends(get_context)]


async def authenticated_device(conn: HTTPConnection, ctx: AppContext) -> Device | None:
    """Authenticate with `Authorization: Bearer <token>` or the `harness_token` cookie."""
    scheme, _, credentials = conn.headers.get("authorization", "").partition(" ")
    token = credentials.strip() if scheme.lower() == "bearer" else conn.cookies.get(COOKIE_NAME)
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
