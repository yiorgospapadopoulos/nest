"""Websocket event stream: replay from `after`, then live events, as JSON text frames."""

import asyncio
from contextlib import aclosing
from typing import Annotated

from fastapi import APIRouter, Query, WebSocket

from harness.api.deps import Context, authenticated_device
from harness.events.bus import EventBus, SubscriptionOverflowError

UNAUTHENTICATED_CLOSE_CODE = 4401
# RFC 6455 "Try Again Later": the client should reconnect with `after`.
OVERFLOW_CLOSE_CODE = 1013

router = APIRouter()


@router.websocket("/api/events")
async def events(
    websocket: WebSocket, ctx: Context, after: Annotated[int | None, Query(ge=0)] = None
) -> None:
    device = await authenticated_device(websocket, ctx)
    # Accept first so the client sees the 4401 close code rather than a bare 403.
    await websocket.accept()
    if device is None:
        await websocket.close(UNAUTHENTICATED_CLOSE_CODE, "not authenticated")
        return
    # Whichever finishes first (stream ended or client gone) cancels the other.
    async with asyncio.TaskGroup() as group:
        stream = group.create_task(_forward(websocket, ctx.bus, after))
        disconnect = group.create_task(_wait_for_disconnect(websocket))
        stream.add_done_callback(lambda _: disconnect.cancel())
        disconnect.add_done_callback(lambda _: stream.cancel())


async def _forward(websocket: WebSocket, bus: EventBus, after: int | None) -> None:
    async with aclosing(bus.subscribe(after)) as subscription:
        try:
            while True:
                event = await anext(subscription)
                await websocket.send_text(event.model_dump_json())
        except SubscriptionOverflowError as error:
            await websocket.close(OVERFLOW_CLOSE_CODE, str(error))


async def _wait_for_disconnect(websocket: WebSocket) -> None:
    # Incoming messages are ignored; this only notices when the client goes away.
    while (await websocket.receive())["type"] != "websocket.disconnect":
        pass
