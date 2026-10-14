"""The `[stuck]` thresholds of settings.toml, for clients to show and edit (D036)."""

from fastapi import APIRouter

from nestd.api.deps import Context, RequireDevice
from nestd.config.errors import ConfigError
from nestd.config.loader import save_stuck
from nestd.config.models import StuckSettings
from nestd.errors import ConflictError

router = APIRouter(prefix="/api/stuck", dependencies=[RequireDevice])


@router.get("/settings")
async def get_settings(ctx: Context) -> StuckSettings:
    return ctx.settings.stuck


@router.put("/settings")
async def put_settings(body: StuckSettings, ctx: Context) -> StuckSettings:
    """Replace the `[stuck]` section of settings.toml; applies at the next check."""
    try:
        saved = save_stuck(ctx.paths, body)
    except ConfigError as error:
        raise ConflictError(str(error)) from error
    ctx.settings = ctx.settings.model_copy(update={"stuck": saved})
    return saved
