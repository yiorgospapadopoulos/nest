"""The first run (B106): with nothing signed in and no local model, clients offer to sign
in or to use local models only.
"""

from fastapi import APIRouter

from nestd.api.deps import Context, RequireDevice
from nestd.local.models import SetupState

router = APIRouter(prefix="/api/setup", dependencies=[RequireDevice])


@router.get("")
async def setup_state(ctx: Context) -> SetupState:
    return await ctx.local.setup()


@router.post("/local-only")
async def use_local_only(ctx: Context) -> SetupState:
    """Use local models only: no sign in is asked for, and the first run is over."""
    return await ctx.local.use_local_only()


@router.post("/done")
async def setup_done(ctx: Context) -> SetupState:
    return await ctx.local.finish_setup()
