from fastapi import APIRouter, Response, status

from nestd.api.deps import Context, RequireDevice
from nestd.claude_sessions.models import ClaudeChat, SetChatArchived
from nestd.events.models import Event
from nestd.sessions.models import Session

router = APIRouter(prefix="/api/claude-chats", dependencies=[RequireDevice])


@router.get("")
async def list_claude_chats(
    ctx: Context, repo: str | None = None, include_automated: bool = False
) -> list[ClaudeChat]:
    """Claude Code chats of the registered repos (or one) that Nest does not own.

    Chats a program started through an Agent SDK are left out unless include_automated.
    """
    return await ctx.claude_chats.list_chats(repo, include_automated)


@router.get("/{chat_id}")
async def get_claude_chat(chat_id: str, ctx: Context) -> ClaudeChat:
    return await ctx.claude_chats.get(chat_id)


@router.put("/{chat_id}/archived")
async def set_claude_chat_archived(
    chat_id: str, request: SetChatArchived, ctx: Context
) -> ClaudeChat:
    """Archive or restore the chat in Nest only (D040); it stays listed, marked."""
    return await ctx.claude_chats.set_archived(chat_id, archived=request.archived)


@router.get("/{chat_id}/events")
async def claude_chat_events(chat_id: str, ctx: Context) -> list[Event]:
    """The transcript, read only, as session events numbered from 1."""
    return await ctx.claude_chats.history(chat_id)


@router.post("/{chat_id}/adopt", status_code=status.HTTP_201_CREATED)
async def adopt_claude_chat(chat_id: str, ctx: Context, response: Response) -> Session:
    """Continue the chat in Nest; a chat Nest already continues returns its session."""
    existing = await ctx.sessions.find_by_provider_session(chat_id)
    if existing is not None:
        response.status_code = status.HTTP_200_OK
        return existing
    session = await ctx.sessions.adopt(await ctx.claude_chats.importable(chat_id))
    # It is Nest's now, so it leaves the Claude Code list.
    await ctx.claude_chats.refresh()
    return session
