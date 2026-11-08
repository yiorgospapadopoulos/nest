"""The `[worktrees]` section of settings.toml, for clients to show and edit (B141)."""

from fastapi import APIRouter

from nestd.api.deps import Context, RequireDevice
from nestd.config.errors import ConfigError
from nestd.config.loader import save_worktrees
from nestd.config.models import WorktreeDefaults
from nestd.errors import ConflictError

router = APIRouter(prefix="/api/worktrees", dependencies=[RequireDevice])


@router.get("/settings")
async def get_settings(ctx: Context) -> WorktreeDefaults:
    return ctx.settings.worktrees


@router.put("/settings")
async def put_settings(body: WorktreeDefaults, ctx: Context) -> WorktreeDefaults:
    """Replace the `[worktrees]` section of settings.toml; applies to the next worktree."""
    try:
        saved = save_worktrees(ctx.paths, body)
    except ConfigError as error:
        raise ConflictError(str(error)) from error
    ctx.settings = ctx.settings.model_copy(update={"worktrees": saved})
    return saved
