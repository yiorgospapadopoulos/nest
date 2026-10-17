"""Storage in Settings (D104): space used, the auto archive setting, large attachments."""

import asyncio
from typing import Annotated

from fastapi import APIRouter, Query

from nestd.api.deps import Context, RequireDevice
from nestd.attachments.store import StoredAttachment
from nestd.config.errors import ConfigError
from nestd.config.loader import save_storage
from nestd.config.models import StorageSettings
from nestd.errors import ConflictError
from nestd.storage.space import StorageUsage, measure

router = APIRouter(prefix="/api/storage", dependencies=[RequireDevice])


@router.get("")
async def storage_usage(ctx: Context) -> StorageUsage:
    """Bytes used in the data folder: chats (the database), attachments, artifacts, other."""
    return await asyncio.to_thread(measure, ctx.paths)


@router.get("/settings")
async def get_settings(ctx: Context) -> StorageSettings:
    return ctx.settings.storage


@router.put("/settings")
async def put_settings(body: StorageSettings, ctx: Context) -> StorageSettings:
    """Replace the `[storage]` section of settings.toml; applies at once."""
    try:
        saved = save_storage(ctx.paths, body)
    except ConfigError as error:
        raise ConflictError(str(error)) from error
    ctx.settings = ctx.settings.model_copy(update={"storage": saved})
    ctx.archiver.wake()
    return saved


@router.get("/attachments")
async def largest_attachments(
    ctx: Context, limit: Annotated[int, Query(ge=1, le=200)] = 20
) -> list[StoredAttachment]:
    """The largest attachments first, with the chat each belongs to."""
    return await ctx.attachments.largest(limit)
