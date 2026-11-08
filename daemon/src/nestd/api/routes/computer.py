"""Computer use (B150): its settings and status, a chat's switch and Stop, and the latest
screenshot of what the chat uses."""

from typing import Literal

from fastapi import APIRouter, Response
from pydantic import BaseModel

from nestd.api.deps import Context, RequireDevice
from nestd.api.routes.attachments import SAFE_HEADERS
from nestd.computer.service import ComputerStatus
from nestd.config.errors import ConfigError
from nestd.config.loader import save_computer_use
from nestd.config.models import ComputerUseSettings
from nestd.errors import ConflictError, NotFoundError
from nestd.sessions.models import Session

router = APIRouter(prefix="/api", dependencies=[RequireDevice])


class PermissionAnswer(BaseModel):
    granted: bool


@router.get("/computer/status")
async def get_status(ctx: Context) -> ComputerStatus:
    return await ctx.computer.status()


@router.post("/computer/permissions/{name}")
async def ask_permission(
    name: Literal["accessibility", "screen_recording"], ctx: Context
) -> PermissionAnswer:
    """Asks macOS through the helper and opens the matching System Settings pane."""
    return PermissionAnswer(granted=await ctx.computer.ask_permission(name))


@router.get("/computer/settings")
async def get_settings(ctx: Context) -> ComputerUseSettings:
    return ctx.settings.computer_use


@router.put("/computer/settings")
async def put_settings(body: ComputerUseSettings, ctx: Context) -> ComputerUseSettings:
    """Replace `[computer_use]`; the master switch and pixies apply at each call."""
    try:
        saved = save_computer_use(ctx.paths, body)
    except ConfigError as error:
        raise ConflictError(str(error)) from error
    ctx.settings = ctx.settings.model_copy(update={"computer_use": saved})
    return saved


@router.post("/sessions/{session_id}/computer/stop")
async def stop(session_id: str, ctx: Context) -> Session:
    """Stop: the chat lets go of what it uses and asks again next time; its turn stops."""
    return await ctx.computer.stop(session_id)


@router.get("/sessions/{session_id}/computer/frame")
async def frame(session_id: str, ctx: Context) -> Response:
    shot = ctx.computer.frame(session_id)
    if shot is None:
        raise NotFoundError("No screenshot yet.")
    return Response(
        shot.png,
        media_type="image/png",
        headers={**SAFE_HEADERS, "Cache-Control": "no-store", "X-Nest-Frame": str(shot.seq)},
    )
