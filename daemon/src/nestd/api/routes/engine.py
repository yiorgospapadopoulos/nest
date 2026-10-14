"""The models and account Claude Code reports, for clients' pickers and profile (D038)."""

from fastapi import APIRouter

from nestd.api.deps import Context, RequireDevice
from nestd.engine.models import ModelList
from nestd.providers.base import AccountInfo

router = APIRouter(prefix="/api", dependencies=[RequireDevice])


@router.get("/models")
async def list_models(ctx: Context) -> ModelList:
    """Claude Code's model list in its order; its aliases until the engine reported one."""
    return await ctx.engine.models()


@router.get("/account")
async def account(ctx: Context) -> AccountInfo:
    """Who Claude Code is signed in as; all null until the engine reported it."""
    return await ctx.engine.account()
