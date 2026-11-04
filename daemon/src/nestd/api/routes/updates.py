"""Engine updates: an app asks for a check when it opens; Relaunch and Undo end the daemon
like `POST /api/service/restart`, and the boot switch does the rest.
"""

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, status

from nestd.api.deps import Context, RequireDevice
from nestd.api.routes.service import get_restart
from nestd.api.schemas import Restarting
from nestd.service.restart import Restarter
from nestd.updates.service import EngineUpdates

router = APIRouter(prefix="/api/updates", dependencies=[RequireDevice])


@router.get("")
async def updates(ctx: Context) -> EngineUpdates:
    return await ctx.updates.status()


@router.post("/check", status_code=status.HTTP_202_ACCEPTED)
async def check(ctx: Context) -> EngineUpdates:
    return await ctx.updates.check()


@router.post("/relaunch", status_code=status.HTTP_202_ACCEPTED)
async def relaunch(
    ctx: Context, background: BackgroundTasks, restart: Annotated[Restarter, Depends(get_restart)]
) -> Restarting:
    await ctx.updates.relaunch()
    background.add_task(restart)
    return Restarting(restarting=True)


@router.post("/undo", status_code=status.HTTP_202_ACCEPTED)
async def undo(
    ctx: Context, background: BackgroundTasks, restart: Annotated[Restarter, Depends(get_restart)]
) -> Restarting:
    await ctx.updates.undo()
    background.add_task(restart)
    return Restarting(restarting=True)


@router.post("/dismiss")
async def dismiss(ctx: Context) -> EngineUpdates:
    return await ctx.updates.dismiss()
