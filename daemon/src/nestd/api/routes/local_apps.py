from pathlib import Path

from fastapi import APIRouter, Response, status
from pydantic import BaseModel, ConfigDict

from nestd.api.deps import Context, RequireDevice
from nestd.config.errors import ConfigError
from nestd.config.loader import save_editors
from nestd.config.models import EditorSettings
from nestd.errors import ConflictError
from nestd.local_apps.apps import OpenTarget
from nestd.local_apps.editors import EditorId

router = APIRouter(prefix="/api", dependencies=[RequireDevice])


class OpenRepo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    app: OpenTarget


class ClaudeCodeOpened(BaseModel):
    launcher: Path
    # Set while Nest runs the session too.
    warning: str | None


class EditorItem(BaseModel):
    id: EditorId
    name: str


class Editors(BaseModel):
    """The editors installed on this computer, in Open in's order (B152)."""

    installed: list[EditorItem]
    # The one Open in's shortcut uses: the chosen one while installed, else the first.
    default: EditorId | None


@router.post("/sessions/{session_id}/open-in-claude-code")
async def open_in_claude_code(session_id: str, ctx: Context) -> ClaudeCodeOpened:
    session = await ctx.sessions.get(session_id)
    await ctx.sessions.close_idle_run(session_id)
    launch = await ctx.local_apps.open_in_claude_code(session, ctx.sessions.has_run(session_id))
    return ClaudeCodeOpened(launcher=launch.launcher, warning=launch.warning)


@router.post("/repos/{name}/open", status_code=status.HTTP_204_NO_CONTENT)
async def open_repo(name: str, body: OpenRepo, ctx: Context) -> Response:
    path = ctx.repos.get(name).path
    await ctx.local_apps.open_repo(path, body.app, ctx.settings.editors.default)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/editors")
async def list_editors(ctx: Context) -> Editors:
    return await _editors(ctx)


@router.put("/editors/default")
async def put_default_editor(body: EditorSettings, ctx: Context) -> Editors:
    """Replace the `[editors]` section of settings.toml; applies at once."""
    try:
        saved = save_editors(ctx.paths, body)
    except ConfigError as error:
        raise ConflictError(str(error)) from error
    ctx.settings = ctx.settings.model_copy(update={"editors": saved})
    return await _editors(ctx)


async def _editors(ctx: Context) -> Editors:
    installed = await ctx.local_apps.installed_editors()
    default = await ctx.local_apps.default_editor(ctx.settings.editors.default)
    return Editors(
        installed=[EditorItem(id=editor.id, name=editor.name) for editor in installed],
        default=None if default is None else default.id,
    )
