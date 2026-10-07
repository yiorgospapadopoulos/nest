from fastapi import APIRouter, Response, status

from harness.api.deps import Context, RequireDevice
from harness.claude_sessions.models import ClaudeChat
from harness.events.models import Event
from harness.sessions.models import Session

router = APIRouter(prefix="/api/claude-chats", dependencies=[RequireDevice])


@router.get("")
async def list_claude_chats(
    ctx: Context, repo: str | None = None, include_automated: bool = False
) -> list[ClaudeChat]:
    """Claude Code chats of the registered repos (or one) that harness does not own.

    Chats a program started through an Agent SDK are left out unless include_automated.
    """
    return await ctx.claude_chats.list_chats(repo, include_automated)


@router.get("/{chat_id}")
async def get_claude_chat(chat_id: str, ctx: Context) -> ClaudeChat:
    return await ctx.claude_chats.get(chat_id)


@router.get("/{chat_id}/events")
async def claude_chat_events(chat_id: str, ctx: Context) -> list[Event]:
    """The transcript, read only, as session events numbered from 1."""
    return await ctx.claude_chats.history(chat_id)


@router.post("/{chat_id}/adopt", status_code=status.HTTP_201_CREATED)
async def adopt_claude_chat(chat_id: str, ctx: Context, response: Response) -> Session:
    """Continue the chat in harness; a chat harness already continues returns its session."""
    existing = await ctx.sessions.find_by_provider_session(chat_id)
    if existing is not None:
        response.status_code = status.HTTP_200_OK
        return existing
    session = await ctx.sessions.adopt(await ctx.claude_chats.importable(chat_id))
    # It is harness's now, so it leaves the Claude Code list.
    await ctx.claude_chats.refresh()
    return session
