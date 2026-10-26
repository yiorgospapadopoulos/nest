"""A chat's folder's dev server run (B108). Chats in the same folder share it."""

from fastapi import APIRouter

from nestd.api.deps import Context, RequireDevice
from nestd.runs.models import RunOutput, RunStatus

router = APIRouter(prefix="/api/sessions", dependencies=[RequireDevice])


@router.get("/{session_id}/run")
async def run_status(session_id: str, ctx: Context) -> RunStatus:
    return await ctx.runs.status(await ctx.sessions.get(session_id))


@router.post("/{session_id}/run/start")
async def start_run(session_id: str, ctx: Context) -> RunStatus:
    """A run that is alive already stays as it is. 409 when `available` is false."""
    return await ctx.runs.start(await ctx.sessions.get(session_id))


@router.post("/{session_id}/run/stop")
async def stop_run(session_id: str, ctx: Context) -> RunStatus:
    """SIGTERM, then SIGKILL after 5 seconds. A run that is not alive stays as it is."""
    return await ctx.runs.stop(await ctx.sessions.get(session_id))


@router.post("/{session_id}/run/restart")
async def restart_run(session_id: str, ctx: Context) -> RunStatus:
    """Stop, then start with the repo's command as it is now. 409 when `available` is
    false.
    """
    return await ctx.runs.restart(await ctx.sessions.get(session_id))


@router.get("/{session_id}/run/output")
async def run_output(session_id: str, ctx: Context) -> RunOutput:
    """The last 2000 lines, raw; `run.output` events bring what follows."""
    return await ctx.runs.output(await ctx.sessions.get(session_id))
