from pathlib import Path

from fastapi import APIRouter, Response, status
from pydantic import BaseModel, ConfigDict

from harness.api.deps import Context, RequireDevice
from harness.local_apps.apps import RepoApp

router = APIRouter(prefix="/api", dependencies=[RequireDevice])


class OpenRepo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    app: RepoApp


class ClaudeCodeOpened(BaseModel):
    launcher: Path
    # Set while harness runs the session too.
    warning: str | None


@router.post("/sessions/{session_id}/open-in-claude-code")
async def open_in_claude_code(session_id: str, ctx: Context) -> ClaudeCodeOpened:
    session = await ctx.sessions.get(session_id)
    launch = await ctx.local_apps.open_in_claude_code(session, ctx.sessions.has_run(session_id))
    return ClaudeCodeOpened(launcher=launch.launcher, warning=launch.warning)


@router.post("/repos/{name}/open", status_code=status.HTTP_204_NO_CONTENT)
async def open_repo(name: str, body: OpenRepo, ctx: Context) -> Response:
    await ctx.local_apps.open_repo(ctx.repos.get(name).path, body.app)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
