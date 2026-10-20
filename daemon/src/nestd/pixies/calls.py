"""The pixies each project chat calls (B46): recorded as the chat's run reports its calls,
continued when tagged again, and shown as the chat's group.

A call is an Agent call whose subagent is a pixie the run offers, or a call of Nest's
call tool, which runs the pixie as a session of its own (B91). Claude Code names the
subagent's agent id in the call's result (or its task's start); a SendMessage to that id
continues the same agent with its context, as another call of that pixie that ends with
its task. Pixie chats offer no pixies to record (`ChatAgents.pixies` is empty there).

The main agent calls solo pixies and team leaders; a leader, inside its own call, calls
and continues its team's members (B70). Those calls are recorded from the leader's
messages; every other subagent's calls are left alone.
"""

import json
import re
from typing import Literal, cast

from pydantic import JsonValue

from nestd.events import types
from nestd.events.bus import EventBus
from nestd.pixies.call_models import (
    CallEntry,
    CallState,
    CallWork,
    GroupEntry,
    PixieCall,
    SendAway,
    TeamMember,
)
from nestd.pixies.call_store import CallStore
from nestd.pixies.models import PixieTeam
from nestd.pixies.store import PixieStore
from nestd.pixies.team_store import TeamStore
from nestd.providers.base import (
    AGENT_TOOLS,
    AgentTask,
    MessageBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from nestd.providers.claude_tools import CALL_TOOL
from nestd.sessions.errors import AgentCallNotFoundError
from nestd.sessions.models import Session, SessionState
from nestd.sessions.subagents import ChatAgents, OfferedPixie
from nestd.tracking.transcripts import ASYNC_LAUNCH, SEND_MESSAGE, AgentWork, agent_work

# Checked live (B46): with this note the chat continued the agent instead of a new one.
CONTINUE_NOTE = (
    "\n\n(@{slug} was called earlier in this chat as agent {agent_id}. Continue that agent"
    " with SendMessage to '{agent_id}' instead of starting a new one.)"
)
CHANGED_MEMBERS_NOTE = (
    "\n\n(Since @{leader} last called them, these members of @{handle} changed: {members}."
    " Tell @{leader} to call them fresh with the Agent tool instead of continuing them.)"
)
# How Claude Code names the subagent in a call's result.
_AGENT_ID = re.compile(r"agentId:\s*([\w-]+)")
_ENDED: dict[str | None, CallState] = {"completed": "done", "failed": "failed"}
# States that end a turn's calls; a closed chat ends the background ones too.
_CUT_OFF = frozenset({SessionState.FAILED, SessionState.INTERRUPTED})


class PixieCallLog:
    def __init__(
        self, store: CallStore, pixies: PixieStore, teams: TeamStore, bus: EventBus
    ) -> None:
        self._store = store
        self._pixies = pixies
        self._teams = teams
        self._bus = bus

    async def note(self, session_id: str, agents: ChatAgents, text: str) -> str:
        """For each solo pixie `text` calls, and the leader of each team it calls, whose
        agent in this chat can be continued: not sent away, and still defined as when it
        was first called. A continued leader hears which members it called have changed.
        """
        members = agents.team_members(text)
        notes: list[str] = []
        for pixie in agents.mentioned_pixies(text) + [p for p in members if p.leader]:
            call = await self._store.latest_agent(session_id, pixie.id)
            if call is None or call.fingerprint != agents.pixie_fingerprint(pixie.slug):
                continue
            notes.append(CONTINUE_NOTE.format(slug=pixie.slug, agent_id=call.agent_id))
            team = [m for m in members if m.team_id == pixie.team_id and not m.leader]
            changed = [m.slug for m in team if await self._changed(session_id, agents, m)]
            if changed:
                notes.append(
                    CHANGED_MEMBERS_NOTE.format(
                        leader=pixie.slug, handle=pixie.team_handle, members=", ".join(changed)
                    )
                )
        return "".join(notes)

    async def message(
        self,
        session_id: str,
        agents: ChatAgents,
        blocks: list[MessageBlock],
        parent_tool_use_id: str | None,
    ) -> None:
        if not agents.pixies:
            return
        if parent_tool_use_id is None:
            allowed = None if agents.rules is None else agents.rules.main
        else:
            allowed = await self._leads(session_id, agents, parent_tool_use_id)
            if allowed is None:
                return
        nested = parent_tool_use_id is not None
        changed = False
        for block in blocks:
            if isinstance(block, ToolUseBlock):
                changed = await self._called(session_id, agents, block, allowed, nested) or changed
            elif isinstance(block, ToolResultBlock):
                changed = await self._returned(session_id, block) or changed
        if changed:
            await self._announce(session_id)

    async def task(self, session_id: str, agents: ChatAgents, update: AgentTask) -> None:
        if not agents.pixies:
            return
        if update.phase == "started":
            changed = await self._task_started(session_id, update)
        elif update.phase == "backgrounded":
            changed = await self._backgrounded(session_id, update.task_id)
        else:
            changed = await self._task_finished(session_id, update)
        if changed:
            await self._announce(session_id)

    async def state_changed(self, session: Session) -> None:
        """A turn cut off ends its calls; background ones go on until the chat closes."""
        if session.state not in _CUT_OFF and session.state is not SessionState.CLOSED:
            return
        if await self._store.interrupt(session.id, session.state is SessionState.CLOSED):
            await self._announce(session.id)

    async def purged(self, session_id: str) -> None:
        """A deleted chat's calls are deleted with it."""

    async def stop_stale(self) -> None:
        """On start: calls a previous process left running ended with it."""
        for session_id in await self._store.interrupt_all():
            await self._announce(session_id)

    async def group(self, session_id: str) -> list[GroupEntry]:
        """The chat's solo pixies and teams, in the order first called."""
        calls = list(reversed(await self._store.in_group(session_id)))
        teams = {team.id: team for team in await self._teams.list_teams()}
        keyed: dict[tuple[Literal["pixie", "team"], str], list[PixieCall]] = {}
        for call in calls:
            team = None if call.team_id is None else teams.get(call.team_id)
            key = ("team", team.id) if team is not None else ("pixie", call.pixie_id)
            keyed.setdefault(key, []).insert(0, call)
        entries: list[GroupEntry] = []
        for (kind, key_id), entry_calls in keyed.items():
            members = [] if kind == "pixie" else await self._members(teams[key_id], entry_calls)
            entries.append(
                GroupEntry(
                    kind=kind,
                    pixie_id=key_id if kind == "pixie" else None,
                    team_id=key_id if kind == "team" else None,
                    state=_state(entry_calls),
                    members=members,
                    calls=[CallEntry.of(call) for call in entry_calls],
                )
            )
        return entries

    async def groups(self) -> dict[str, list[GroupEntry]]:
        """Every chat's group that is not empty, by chat."""
        return {
            session_id: await self.group(session_id)
            for session_id in await self._store.chats_in_group()
        }

    async def calls(self, session_id: str, pixie_id: str) -> list[CallWork]:
        """Every call to the pixie in the chat's group, newest first, with its work."""
        calls = await self._store.in_group(session_id, pixie_id)
        by_agent: dict[str, list[str]] = {}
        for call in reversed(calls):
            by_agent.setdefault(call.continues or call.tool_use_id, []).append(call.tool_use_id)
        events = await self._bus.session_events(session_id)
        works = {
            work.tool_use_id: work
            for parent, tool_uses in by_agent.items()
            for work in agent_work(events, parent, tool_uses)
        }
        return [_work(call, works.get(call.tool_use_id)) for call in calls]

    async def agent_transcript(self, session_id: str, tool_use_id: str) -> AgentWork:
        """Any subagent's own transcript, by its Agent call."""
        events = await self._bus.session_events(session_id)
        works = agent_work(events, tool_use_id, [tool_use_id])
        if not works:
            msg = f"no agent call {tool_use_id!r} in this chat"
            raise AgentCallNotFoundError(msg)
        return works[0]

    async def send_away(self, session_id: str, request: SendAway) -> list[GroupEntry]:
        """The pixie, or the team with its members, leaves the chat's group and its agents
        are no longer continued; calling it again brings it back, fresh.
        """
        if request.pixie_id is not None:
            pixie_ids = [request.pixie_id]
        else:
            assert request.team_id is not None  # noqa: S101 (SendAway names one)
            pixie_ids = [pixie.id for pixie in await self._pixies.members(request.team_id)]
        if await self._store.send_away(session_id, pixie_ids, request.team_id):
            await self._announce(session_id)
        return await self.group(session_id)

    async def _changed(self, session_id: str, agents: ChatAgents, pixie: OfferedPixie) -> bool:
        call = await self._store.latest_agent(session_id, pixie.id)
        return call is not None and call.fingerprint != agents.pixie_fingerprint(pixie.slug)

    async def _leads(
        self, session_id: str, agents: ChatAgents, parent_tool_use_id: str
    ) -> frozenset[str] | None:
        """The members the subagent whose message this is may call: its team's when it is
        a leader called in this chat, else None.
        """
        if agents.rules is None:
            return None
        call = await self._store.by_tool_use(session_id, parent_tool_use_id)
        if call is None:
            return None
        slug = next((p.slug for p in agents.pixies.values() if p.id == call.pixie_id), None)
        return None if slug is None else agents.rules.leaders.get(slug)

    async def _called(
        self,
        session_id: str,
        agents: ChatAgents,
        block: ToolUseBlock,
        allowed: frozenset[str] | None,
        nested: bool,
    ) -> bool:
        """`allowed` names the pixies the caller may call (None: any); the call guard
        refuses the others. A leader's calls of its members run in the foreground.
        """
        if block.name in AGENT_TOOLS or block.name == CALL_TOOL:
            slug = block.input.get("subagent_type" if block.name in AGENT_TOOLS else "pixie")
            pixie = agents.pixies.get(slug) if isinstance(slug, str) else None
            if pixie is None or (allowed is not None and pixie.slug not in allowed):
                return False
            await self._store.add(
                session_id=session_id,
                pixie_id=pixie.id,
                team_id=pixie.team_id,
                tool_use_id=block.id,
                fingerprint=agents.pixie_fingerprint(pixie.slug),
                background=not nested and block.input.get("run_in_background") is True,
            )
            return True
        to = block.input.get("to") if block.name == SEND_MESSAGE else None
        earlier = None if not isinstance(to, str) else await self._store.by_agent(session_id, to)
        if earlier is None or (nested and not _among(agents, earlier.pixie_id, allowed)):
            return False
        await self._store.add(
            session_id=session_id,
            pixie_id=earlier.pixie_id,
            team_id=earlier.team_id,
            tool_use_id=block.id,
            fingerprint=earlier.fingerprint,
            background=True,
            agent_id=earlier.agent_id,
            continues=earlier.continues or earlier.tool_use_id,
        )
        return True

    async def _returned(self, session_id: str, block: ToolResultBlock) -> bool:
        """A call's result: a foreground call's end; a background call or a SendMessage
        only started, unless it could not.
        """
        call = await self._store.by_tool_use(session_id, block.tool_use_id)
        if call is None or call.state != "running":
            return False
        changes: dict[str, object] = {}
        found = _AGENT_ID.search(block.content)
        if found is not None and call.agent_id is None:
            changes["agent_id"] = found.group(1)
        background = call.background or ASYNC_LAUNCH in block.content
        if background and not call.background:
            changes["background"] = True
        if block.is_error or (call.continues is not None and _refused(block.content)):
            await self._store.finish(call.id, "failed", **changes)
        elif not background:
            await self._store.finish(call.id, "done", **changes)
        elif changes:
            await self._store.update(call.id, **changes)
        else:
            return False
        return True

    async def _task_started(self, session_id: str, update: AgentTask) -> bool:
        if update.tool_use_id is None:
            return False
        call = await self._store.by_tool_use(session_id, update.tool_use_id)
        if call is None or call.agent_id is not None:
            return False
        await self._store.update(
            call.id, agent_id=update.task_id, background=call.background or update.background
        )
        return True

    async def _backgrounded(self, session_id: str, task_id: str) -> bool:
        call = await self._store.by_agent(session_id, task_id, running=True)
        if call is None or call.background:
            return False
        await self._store.update(call.id, background=True)
        return True

    async def _task_finished(self, session_id: str, update: AgentTask) -> bool:
        """A background call or a SendMessage ends with its task; a foreground call with
        its result.
        """
        call = await self._store.by_agent(session_id, update.task_id, running=True)
        if call is None or not call.background:
            return False
        await self._store.finish(call.id, _ENDED.get(update.status, "interrupted"))
        return True

    async def _members(self, team: PixieTeam, calls: list[PixieCall]) -> list[TeamMember]:
        """Its pixies now, then any it called that left it; each with its latest state."""
        latest: dict[str, CallState] = {}
        for call in calls:
            latest.setdefault(call.pixie_id, call.state)
        ids = [pixie.id for pixie in await self._pixies.members(team.id)]
        ids += [pixie_id for pixie_id in latest if pixie_id not in ids]
        return [
            TeamMember(
                pixie_id=pixie_id, leader=pixie_id == team.leader_id, state=latest.get(pixie_id)
            )
            for pixie_id in ids
        ]

    async def _announce(self, session_id: str) -> None:
        group: list[JsonValue] = [
            entry.model_dump(mode="json") for entry in await self.group(session_id)
        ]
        await self._bus.publish(types.SESSION_PIXIES, {"group": group}, session_id)


def _among(agents: ChatAgents, pixie_id: str, allowed: frozenset[str] | None) -> bool:
    """Whether the pixie is offered under one of the `allowed` slugs."""
    return any(p.id == pixie_id and p.slug in (allowed or ()) for p in agents.pixies.values())


def _state(calls: list[PixieCall]) -> CallState:
    """Working while any call runs: a team's leader outlasts its members' calls (B70);
    else the newest call's.
    """
    return "running" if any(call.state == "running" for call in calls) else calls[0].state


def _refused(content: str) -> bool:
    """A SendMessage result that says the agent was not resumed."""
    try:
        data: object = json.loads(content)
    except ValueError:
        return False
    return isinstance(data, dict) and cast("dict[str, object]", data).get("success") is False


def _work(call: PixieCall, work: AgentWork | None) -> CallWork:
    """A call whose messages are gone, as after a rewind, has only its state."""
    entry = CallEntry.of(call).model_dump()
    if work is None:
        return CallWork(**entry, prompt=None, messages=[], report=None)
    return CallWork(**entry, prompt=work.prompt, messages=work.messages, report=work.report)
