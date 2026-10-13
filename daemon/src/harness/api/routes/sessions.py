from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from harness.api.deps import Context, RequireDevice
from harness.api.schemas import FileList, SessionDetail
from harness.events.models import Event
from harness.sessions.commands import CommandList
from harness.sessions.errors import PixieChatError
from harness.sessions.models import CreateSession, SendMessage, SendResult, Session, UpdateSession

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
    return SessionDetail(
        **session.model_dump(),
        tasks=tracked.tasks,
        agents=tracked.agents,
        background=tracked.background,
        queued=await ctx.sessions.queued(session_id),
    )


@router.get("/{session_id}/events")
async def session_events(
    session_id: str,
    ctx: Context,
    after: Annotated[int, Query(ge=0)] = 0,
    before: Annotated[int | None, Query(ge=1)] = None,
    limit: Annotated[int | None, Query(ge=1, le=1000)] = None,
) -> list[Event]:
    """The persisted transcript, oldest first; live updates (including text deltas) come
    over /api/events. Events with after < id < before; with `limit`, the ones nearest
    `before` when it is given, else nearest `after`, so a client can page both ways.
    """
    await ctx.sessions.get(session_id)
    return await ctx.bus.session_events(session_id, after, before, limit)


@router.post("/{session_id}/messages", status_code=status.HTTP_202_ACCEPTED)
async def send_message(session_id: str, body: SendMessage, ctx: Context) -> SendResult:
    """Starts a turn, or queues the message while one runs (`queued_message` is then set).

    With `interrupt`, a running turn is stopped and this message starts right after it.
    """
    return await ctx.sessions.send(session_id, body.text, body.attachment_ids, body.interrupt)


@router.delete("/{session_id}/queue/{message_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_queued(session_id: str, message_id: str, ctx: Context) -> Response:
    await ctx.sessions.cancel_queued(session_id, message_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{session_id}/commands")
async def session_commands(session_id: str, ctx: Context) -> CommandList:
    """The slash commands and agents of the session's agent, or else of its repo's latest."""
    session = await ctx.sessions.get(session_id)
    return await ctx.commands.for_session(session.id, session.repo)


@router.get("/{session_id}/files")
async def session_files(
    session_id: str, ctx: Context, q: Annotated[str, Query(max_length=200)] = ""
) -> FileList:
    """Up to 50 files for an @ mention: tracked or untracked and not ignored."""
    return FileList(files=await ctx.sessions.files(session_id, q))


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
    """Close the session; with purge, delete it with its worktree, branch and history.
    A pixie's chat is refused (409 `pixie_chat`): it goes with its pixie (D057).
    """
    if (await ctx.sessions.get(session_id)).pixie_id is not None:
        raise PixieChatError
    if purge:
        await ctx.sessions.purge(session_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    return await ctx.sessions.close(session_id, remove_worktree)
