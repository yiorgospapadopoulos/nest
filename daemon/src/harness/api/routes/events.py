"""Websocket event stream: replay from `after`, then live events, as JSON text frames."""

import asyncio
from collections.abc import Sequence
from contextlib import aclosing
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import APIRouter, Query, WebSocket

from harness.api.deps import Context, authenticated_device
from harness.events import types
from harness.events.bus import EventBus, SubscriptionOverflowError

UNAUTHENTICATED_CLOSE_CODE = 4401
# A browser page from another origin; native clients send no Origin and are not affected.
FORBIDDEN_ORIGIN_CLOSE_CODE = 4403
# RFC 6455 "Try Again Later": the client should reconnect with `after`.
OVERFLOW_CLOSE_CODE = 1013

router = APIRouter()


@router.websocket("/api/events")
async def events(
    websocket: WebSocket, ctx: Context, after: Annotated[int | None, Query(ge=0)] = None
) -> None:
    origin = websocket.headers.get("origin")
    allowed = origin_allowed(
        origin, websocket.headers.get("host"), ctx.settings.server.allowed_origins
    )
    device = await authenticated_device(websocket, ctx)
    # Accept first so the client sees the 44xx close code rather than a bare 403.
    await websocket.accept()
    if not allowed:
        await websocket.close(FORBIDDEN_ORIGIN_CLOSE_CODE, "origin not allowed")
        return
    if device is None:
        await websocket.close(UNAUTHENTICATED_CLOSE_CODE, "not authenticated")
        return
    # Whichever finishes first (stream ended or client gone) cancels the other.
    async with asyncio.TaskGroup() as group:
        stream = group.create_task(_forward(websocket, ctx.bus, after, device.id))
        disconnect = group.create_task(_wait_for_disconnect(websocket))
        stream.add_done_callback(lambda _: disconnect.cancel())
        disconnect.add_done_callback(lambda _: stream.cancel())


def origin_allowed(origin: str | None, host: str | None, allowed: Sequence[str]) -> bool:
    """No Origin (a native client), the request's own host, or an origin from settings."""
    if origin is None:
        return True
    normalized = origin.rstrip("/").lower()
    if normalized in (entry.rstrip("/").lower() for entry in allowed):
        return True
    parts = urlsplit(normalized)
    return parts.scheme in ("http", "https") and host is not None and parts.netloc == host.lower()


async def _forward(websocket: WebSocket, bus: EventBus, after: int | None, device_id: str) -> None:
    async with aclosing(bus.subscribe(after)) as subscription:
        try:
            while True:
                event = await anext(subscription)
                # The socket was authenticated when it opened; a revoked device stops at
                # once instead of when it next reconnects (D051).
                if event.type == types.DEVICE_REVOKED and (
                    event.payload.get("device_id") == device_id
                ):
                    await websocket.close(UNAUTHENTICATED_CLOSE_CODE, "device revoked")
                    return
                await websocket.send_text(event.model_dump_json())
        except SubscriptionOverflowError as error:
            await websocket.close(OVERFLOW_CLOSE_CODE, str(error))


async def _wait_for_disconnect(websocket: WebSocket) -> None:
    # Incoming messages are ignored; this only notices when the client goes away.
    while (await websocket.receive())["type"] != "websocket.disconnect":
        pass
