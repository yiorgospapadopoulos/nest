"""Pixies: saved agents with a soul, memory and their own chat (D072)."""

from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from harness.api.deps import Context, RequireDevice
from harness.pixies.models import (
    CreatePixie,
    FileText,
    Pixie,
    PixieOrder,
    SearchHit,
    UpdatePixie,
    WriteFile,
)
from harness.sessions.models import SendMessage, SendResult

router = APIRouter(prefix="/api/pixies", dependencies=[RequireDevice])


@router.get("")
async def list_pixies(ctx: Context) -> list[Pixie]:
    return await ctx.pixies.list_pixies()


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_pixie(body: CreatePixie, ctx: Context) -> Pixie:
    return await ctx.pixies.create(body)


@router.put("/order")
async def reorder_pixies(body: PixieOrder, ctx: Context) -> list[Pixie]:
    """Names every pixie once, in the new order (422 otherwise); returns them in it.
    Publishes `pixie.updated` for each pixie whose position changed.
    """
    return await ctx.pixies.reorder(body.ids)


@router.get("/{pixie_id}")
async def get_pixie(pixie_id: str, ctx: Context) -> Pixie:
    return await ctx.pixies.get(pixie_id)


@router.patch("/{pixie_id}")
async def update_pixie(pixie_id: str, body: UpdatePixie, ctx: Context) -> Pixie:
    """`"model": null` or `"effort": null` sets it back to the default. 422 when the model
    does not run in the chosen mode; a pixie in Auto moved to a model without it asks
    again (`default`), as a chat does.
    """
    return await ctx.pixies.update(pixie_id, body)


@router.delete("/{pixie_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_pixie(pixie_id: str, ctx: Context) -> Response:
    """Stops and deletes its chats and removes its soul, memory and notes."""
    await ctx.pixies.delete(pixie_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{pixie_id}/messages", status_code=status.HTTP_202_ACCEPTED)
async def send_to_pixie(pixie_id: str, body: SendMessage, ctx: Context) -> SendResult:
    """Starts the pixie's chat with this message, or sends it to the open one; while a turn
    runs the message is queued and comes back as `queued_message`."""
    return await ctx.pixies.send(pixie_id, body.text, body.attachment_ids)


@router.post("/{pixie_id}/reset")
async def reset_pixie(pixie_id: str, ctx: Context) -> Pixie:
    """Archives the chat; the next message starts a new one. Soul and memory stay."""
    return await ctx.pixies.reset(pixie_id)


@router.get("/{pixie_id}/files/{name:path}")
async def read_file(pixie_id: str, name: str, ctx: Context) -> FileText:
    """`soul`, `memory` or `notes/<name>`."""
    return await ctx.pixies.read_file(pixie_id, name)


@router.put("/{pixie_id}/files/{name:path}")
async def write_file(pixie_id: str, name: str, body: WriteFile, ctx: Context) -> FileText:
    """409 `stale_file` with the current text and hash when `hash` is not the current one."""
    return await ctx.pixies.write_file(pixie_id, name, body)


@router.get("/{pixie_id}/notes")
async def list_notes(pixie_id: str, ctx: Context) -> list[str]:
    return await ctx.pixies.notes(pixie_id)


@router.get("/{pixie_id}/search")
async def search_memory(
    pixie_id: str, ctx: Context, q: Annotated[str, Query(min_length=1, max_length=200)]
) -> list[SearchHit]:
    return await ctx.pixies.search(pixie_id, q)
