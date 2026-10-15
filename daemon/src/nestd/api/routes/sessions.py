from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from nestd.api.deps import Context, RequireDevice
from nestd.api.schemas import FileList, SessionDetail
from nestd.events.models import Event
from nestd.sessions.commands import CommandList
from nestd.sessions.errors import PixieChatError
from nestd.sessions.models import (
    CreateSession,
    ForkReply,
    ForkRequest,
    Restore,
    RewindReply,
    RewindRequest,
    SendMessage,
    SendResult,
    Session,
    UpdateSession,
)

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
    """Remove a pending message. One written into the running turn (`sent`) only while
    Claude has not read it: 409 `message_taken` once it has (B59).
    """
    await ctx.sessions.cancel_queued(session_id, message_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{session_id}/queue/{message_id}/send-now", status_code=status.HTTP_202_ACCEPTED)
async def send_now(session_id: str, message_id: str, ctx: Context) -> Response:
    """Send a pending message now: the running turn is stopped and the message starts right
    after it, first in line; on an idle chat it starts at once (B59).
    """
    await ctx.sessions.send_now(session_id, message_id)
    return Response(status_code=status.HTTP_202_ACCEPTED)


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


@router.post("/{session_id}/tasks/{task_id}/stop", status_code=status.HTTP_202_ACCEPTED)
async def stop_task(session_id: str, task_id: str, ctx: Context) -> Response:
    """Stop one background task or subagent of the chat's agent, not the turn (B59);
    `task_id` is its task id or the id of the Agent or Bash call that started it (the id
    of its row in the session's agents and background). Its end arrives as a
    `session.agent_task` event. 404 for an unknown session or a task that
    is not running, 409 when the chat has no agent running.
    """
    await ctx.sessions.stop_task(session_id, task_id)
    return Response(status_code=status.HTTP_202_ACCEPTED)


@router.get("/{session_id}/rewind")
async def preview_rewind(
    session_id: str,
    ctx: Context,
    message: Annotated[int, Query(ge=1)],
    restore: Restore = "code",
) -> RewindReply:
    """What rewinding to before the user message of event `message` would do: the files it
    would restore (`code`, `both`), and whether Claude Code's transcript can be cut there
    (`conversation`, `both`); `can_rewind` false with `error` when it cannot. 409 unless
    the chat is idle (IMP-02), and 409 `pixie_chat` for a pixie's chat (D072).
    """
    return await ctx.sessions.rewind(session_id, message, dry_run=True, restore=restore)


@router.post("/{session_id}/rewind")
async def rewind(session_id: str, body: RewindRequest, ctx: Context) -> RewindReply:
    """Rewind to before that message, as Claude Code does (B59). `code` restores the files
    the agent changed since (noted in the chat as a `session.notice` of kind
    `files_restored`); `conversation` drops the message and everything after it from the
    chat (a `session.rewound` event) and the next message continues from before it, the
    reply's `text` and `attachments` going back to the composer; `both` does both. 409
    unless the chat is idle, `cannot_rewind` with the reason, or `pixie_chat`.
    """
    return await ctx.sessions.rewind(session_id, body.message, dry_run=False, restore=body.restore)


@router.post("/{session_id}/fork", status_code=status.HTTP_201_CREATED)
async def fork(session_id: str, body: ForkRequest, ctx: Context) -> ForkReply:
    """A new chat whose conversation is this one's up to before the user message of event
    `message`, in the same project and work mode; this chat is untouched (B59). The reply's
    `text` and `attachments` go to the new chat's composer. 409 while a turn runs,
    `cannot_rewind` when the message cannot be forked from, `pixie_chat` for a pixie's.
    """
    return await ctx.sessions.fork(session_id, body.message)


@router.patch("/{session_id}")
async def update_session(session_id: str, body: UpdateSession, ctx: Context) -> Session:
    return await ctx.sessions.update(session_id, body)


@router.delete("/{session_id}", response_model=None)
async def close_session(
    session_id: str, ctx: Context, remove_worktree: bool = False, purge: bool = False
) -> Session | Response:
    """Close the session; with purge, delete it with its worktree, branch and history.
    A pixie's chat is refused (409 `pixie_chat`): it goes with its pixie (D072).
    """
    if (await ctx.sessions.get(session_id)).pixie_id is not None:
        raise PixieChatError
    if purge:
        await ctx.sessions.purge(session_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    return await ctx.sessions.close(session_id, remove_worktree)
