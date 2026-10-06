from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from harness.api.deps import Context, RequireDevice
from harness.api.schemas import SessionDetail
from harness.events.models import Event
from harness.sessions.models import CreateSession, SendMessage, Session, UpdateSession

router = APIRouter(prefix="/api/sessions", dependencies=[RequireDevice])


@router.get("")
async def list_sessions(
    ctx: Context, repo: str | None = None, archived: bool = False
) -> list[Session]:
    """Pinned first, then most recently updated. Archived sessions only with archived=true."""
    return await ctx.sessions.list_sessions(repo, archived)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_session(body: CreateSession, ctx: Context) -> Session:
    return await ctx.sessions.create(body)


@router.get("/{session_id}")
async def get_session(session_id: str, ctx: Context) -> SessionDetail:
    session = await ctx.sessions.get(session_id)
    tracked = await ctx.tracking.snapshot(session_id)
    return SessionDetail(**session.model_dump(), tasks=tracked.tasks, agents=tracked.agents)


@router.get("/{session_id}/events")
async def session_events(
    session_id: str, ctx: Context, after: Annotated[int, Query(ge=0)] = 0
) -> list[Event]:
    """The persisted transcript; live updates (including text deltas) come over /api/events."""
    await ctx.sessions.get(session_id)
    return await ctx.bus.session_events(session_id, after)


@router.post("/{session_id}/messages", status_code=status.HTTP_202_ACCEPTED)
async def send_message(session_id: str, body: SendMessage, ctx: Context) -> Session:
    return await ctx.sessions.send(session_id, body.text, body.attachment_ids)


@router.post("/{session_id}/interrupt", status_code=status.HTTP_202_ACCEPTED)
async def interrupt(session_id: str, ctx: Context) -> Response:
    await ctx.sessions.interrupt(session_id)
    return Response(status_code=status.HTTP_202_ACCEPTED)


@router.patch("/{session_id}")
async def update_session(session_id: str, body: UpdateSession, ctx: Context) -> Session:
    return await ctx.sessions.update(session_id, body)


@router.delete("/{session_id}", response_model=None)
async def close_session(
    session_id: str, ctx: Context, remove_worktree: bool = False, purge: bool = False
) -> Session | Response:
    """Close the session; with purge, delete it with its worktree, branch and history."""
    if purge:
        await ctx.sessions.purge(session_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    return await ctx.sessions.close(session_id, remove_worktree)
