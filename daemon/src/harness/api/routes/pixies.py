"""Pixies: saved agents with a soul, memory and their own chat (D057)."""

from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from harness.api.deps import Context, RequireDevice
from harness.pixies.models import (
    CreatePixie,
    FileText,
    Pixie,
    SearchHit,
    UpdatePixie,
    WriteFile,
)
from harness.sessions.models import SendMessage, Session

router = APIRouter(prefix="/api/pixies", dependencies=[RequireDevice])


@router.get("")
async def list_pixies(ctx: Context) -> list[Pixie]:
    return await ctx.pixies.list_pixies()


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_pixie(body: CreatePixie, ctx: Context) -> Pixie:
    return await ctx.pixies.create(body)


@router.get("/{pixie_id}")
async def get_pixie(pixie_id: str, ctx: Context) -> Pixie:
    return await ctx.pixies.get(pixie_id)


@router.patch("/{pixie_id}")
async def update_pixie(pixie_id: str, body: UpdatePixie, ctx: Context) -> Pixie:
    return await ctx.pixies.update(pixie_id, body)


@router.delete("/{pixie_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_pixie(pixie_id: str, ctx: Context) -> Response:
    """Stops and deletes its chats and removes its soul, memory and notes."""
    await ctx.pixies.delete(pixie_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{pixie_id}/messages", status_code=status.HTTP_202_ACCEPTED)
async def send_to_pixie(pixie_id: str, body: SendMessage, ctx: Context) -> Session:
    """Starts the pixie's chat with this message, or sends it to the open one."""
    return await ctx.pixies.send(pixie_id, body.text, body.attachment_ids)


@router.post("/{pixie_id}/reset")
async def reset_pixie(pixie_id: str, ctx: Context) -> Pixie:
    """Archives the chat; the next message starts a new one. Soul and memory stay."""
    return await ctx.pixies.reset(pixie_id)


@router.get("/{pixie_id}/files/{name:path}")
async def read_file(pixie_id: str, name: str, ctx: Context) -> FileText:
    """`soul`, `memory` or `notes/<name>`."""
    return ctx.pixies.read_file(pixie_id, name)


@router.put("/{pixie_id}/files/{name:path}")
async def write_file(pixie_id: str, name: str, body: WriteFile, ctx: Context) -> FileText:
    """409 `stale_file` with the current text and hash when `hash` is not the current one."""
    return ctx.pixies.write_file(pixie_id, name, body)


@router.get("/{pixie_id}/notes")
async def list_notes(pixie_id: str, ctx: Context) -> list[str]:
    return ctx.pixies.notes(pixie_id)


@router.get("/{pixie_id}/search")
async def search_memory(
    pixie_id: str, ctx: Context, q: Annotated[str, Query(min_length=1, max_length=200)]
) -> list[SearchHit]:
    return ctx.pixies.search(pixie_id, q)
