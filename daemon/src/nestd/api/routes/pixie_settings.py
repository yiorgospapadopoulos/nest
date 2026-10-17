"""What new pixies start with and the habit rules of every pixie: `[pixies]` (D104)."""

from fastapi import APIRouter

from nestd.api.deps import Context, RequireDevice
from nestd.config.errors import ConfigError
from nestd.config.loader import save_pixie_defaults
from nestd.config.models import PixieDefaults
from nestd.errors import ConflictError

router = APIRouter(prefix="/api/pixie-settings", dependencies=[RequireDevice])


@router.get("")
async def get_settings(ctx: Context) -> PixieDefaults:
    return ctx.settings.pixies


@router.put("")
async def put_settings(body: PixieDefaults, ctx: Context) -> PixieDefaults:
    """Replace the `[pixies]` section of settings.toml; applies at once."""
    try:
        saved = save_pixie_defaults(ctx.paths, body)
    except ConfigError as error:
        raise ConflictError(str(error)) from error
    ctx.settings = ctx.settings.model_copy(update={"pixies": saved})
    return saved
