"""The `[notifications]` rules of settings.toml, for clients to show and edit."""

from fastapi import APIRouter

from harness.api.deps import Context, RequireDevice
from harness.config.errors import ConfigError
from harness.config.loader import save_notifications
from harness.config.models import NotificationSettings
from harness.errors import ConflictError

router = APIRouter(prefix="/api/notifications", dependencies=[RequireDevice])


@router.get("/settings")
async def get_settings(ctx: Context) -> NotificationSettings:
    return ctx.settings.notifications


@router.put("/settings")
async def put_settings(body: NotificationSettings, ctx: Context) -> NotificationSettings:
    """Replace the whole section; send back what GET returned with the changes applied."""
    try:
        saved = save_notifications(ctx.paths, body)
    except ConfigError as error:
        raise ConflictError(str(error)) from error
    # Only this section applies live; other edits to the file wait for a restart.
    ctx.settings = ctx.settings.model_copy(update={"notifications": saved})
    return saved
