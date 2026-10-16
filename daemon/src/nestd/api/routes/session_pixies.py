"""Each project chat's pixies and its subagents' own transcripts (B46)."""

from fastapi import APIRouter

from nestd.api.deps import Context, RequireDevice
from nestd.pixies.call_models import CallWork, GroupEntry, SendAway
from nestd.tracking.transcripts import AgentWork

router = APIRouter(prefix="/api/sessions", dependencies=[RequireDevice])


@router.get("/{session_id}/pixies")
async def chat_pixies(session_id: str, ctx: Context) -> list[GroupEntry]:
    """The pixies the chat called and did not send away: solo pixies and teams (with their
    members, the leader marked), in the order first called, each with its calls newest
    first. Live as `session.pixies` events.
    """
    await ctx.sessions.get(session_id)
    return await ctx.pixie_calls.group(session_id)


@router.post("/{session_id}/pixies/send-away")
async def send_away(session_id: str, body: SendAway, ctx: Context) -> list[GroupEntry]:
    """The pixie, or the team with its members, leaves the chat's group and is no longer
    continued; calling it again brings it back, fresh. Returns the group.
    """
    await ctx.sessions.get(session_id)
    return await ctx.pixie_calls.send_away(session_id, body)


@router.get("/{session_id}/pixies/{pixie_id}/calls")
async def pixie_calls(session_id: str, pixie_id: str, ctx: Context) -> list[CallWork]:
    """Every call to the pixie in the chat, newest first, with what it was asked, its own
    messages and its report.
    """
    await ctx.sessions.get(session_id)
    return await ctx.pixie_calls.calls(session_id, pixie_id)


@router.get("/{session_id}/agents/{tool_use_id}/transcript")
async def agent_transcript(session_id: str, tool_use_id: str, ctx: Context) -> AgentWork:
    """Any subagent's own transcript by its Agent call, so far while it runs; clients
    follow it live with the `session.message` events naming the call as their parent.
    404 for a call the chat did not make.
    """
    await ctx.sessions.get(session_id)
    return await ctx.pixie_calls.agent_transcript(session_id, tool_use_id)
