"""The `[limits]` section of settings.toml, for clients to show and edit (D160)."""

from fastapi import APIRouter

from nestd.api.deps import Context, RequireDevice
from nestd.config.errors import ConfigError
from nestd.config.loader import save_limits
from nestd.config.models import LimitSettings
from nestd.errors import ConflictError

router = APIRouter(prefix="/api/limits", dependencies=[RequireDevice])


@router.get("/settings")
async def get_settings(ctx: Context) -> LimitSettings:
    return ctx.settings.limits


@router.put("/settings")
async def put_settings(body: LimitSettings, ctx: Context) -> LimitSettings:
    """Replace the `[limits]` section of settings.toml; applies at each chat's next turn."""
    try:
        saved = save_limits(ctx.paths, body)
    except ConfigError as error:
        raise ConflictError(str(error)) from error
    ctx.settings = ctx.settings.model_copy(update={"limits": saved})
    return saved
