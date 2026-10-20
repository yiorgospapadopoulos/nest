"""Pixie calls across engines (B91 stage 2).

Claude runs a called pixie as a subagent inside the caller's run (B40). Codex takes no
Nest-defined subagents, so where the caller or the called pixie is on Codex the call goes
through Nest's `call_pixie` tool: it starts the pixie as a session of its own, in the
caller's folder and linked to it (`called_by`), with the prompt it would have as a
subagent, waits for that session's first turn to end and returns its last message as the
tool's result, its report. The call rules hold as for subagents (B70): the calling run's
main agent calls solo pixies and leaders, a leader its own members, which Claude's call
guard checks per agent and this tool for Codex runs, whose main agent is the only caller.

The called session is closed once it has reported, or when the call is cancelled (the
caller was stopped or closed), so no agent of it keeps running.
"""

import asyncio
from collections.abc import Callable
from contextlib import suppress

from pydantic import JsonValue

from nestd.config.models import AgentDefaults
from nestd.errors import NestError
from nestd.events import types
from nestd.events.bus import EventBus
from nestd.pixies.models import run_model
from nestd.pixies.store import PixieStore
from nestd.providers.base import CALL_PIXIE_TOOL, AgentTool, CallRules, ToolRefusedError
from nestd.providers.claude_tools import MEMBER_CALL_DENIED
from nestd.sessions.manager import SessionManager
from nestd.sessions.models import Session, SessionState
from nestd.sessions.subagents import ChatAgents

TASK_MAX = 20_000
# The states a called pixie's first turn ends in.
FINISHED = frozenset(
    {SessionState.IDLE, SessionState.FAILED, SessionState.INTERRUPTED, SessionState.CLOSED}
)
_LAST_EVENTS = 400
_NEWEST = 2**62
DESCRIPTION = (
    "Call a pixie, a persistent agent set up in Nest, to do one part of the work, and wait"
    " for its report. It works in this chat's folder in a session of its own. Give it the"
    " whole task: it does not see this conversation. Pixies you can call:\n{pixies}"
)


class PixieCallRuns:
    """The call tool of each run with pixies to call this way, and their sessions."""

    def __init__(
        self,
        *,
        pixies: PixieStore,
        sessions: SessionManager,
        bus: EventBus,
        defaults: Callable[[], AgentDefaults],
    ) -> None:
        """`defaults` gives the model of a Claude pixie without its own, read per call."""
        self._pixies = pixies
        self._sessions = sessions
        self._bus = bus
        self._defaults = defaults
        # By called session: the call waiting for its first turn to end.
        self._waiting: dict[str, asyncio.Future[Session | None]] = {}

    def tools(self, caller: Session, agents: ChatAgents) -> tuple[AgentTool, ...]:
        """The call tool of `caller`'s run; none when it calls no pixie this way."""
        if not agents.tool_calls:
            return ()
        listing = "\n".join(
            f"- {slug}: {agents.subagents[slug].description}" for slug in agents.tool_calls
        )
        schema: dict[str, JsonValue] = {
            "type": "object",
            "properties": {
                "pixie": {
                    "type": "string",
                    "enum": list[JsonValue](agents.tool_calls),
                    "description": "The pixie's slug.",
                },
                "task": {"type": "string", "description": "What the pixie should do."},
            },
            "required": ["pixie", "task"],
        }

        async def call(args: dict[str, JsonValue]) -> str:
            return await self._call(caller, agents, args)

        return (AgentTool(CALL_PIXIE_TOOL, DESCRIPTION.format(pixies=listing), schema, call),)

    async def state_changed(self, session: Session) -> None:
        if session.called_by is None or session.state not in FINISHED:
            return
        waiting = self._waiting.get(session.id)
        if waiting is not None and not waiting.done():
            waiting.set_result(session)

    async def purged(self, session_id: str) -> None:
        waiting = self._waiting.get(session_id)
        if waiting is not None and not waiting.done():
            waiting.set_result(None)

    async def _call(self, caller: Session, agents: ChatAgents, args: dict[str, JsonValue]) -> str:
        slug = args.get("pixie")
        if not isinstance(slug, str) or slug not in agents.tool_calls:
            msg = f"No pixie @{slug} to call with {CALL_PIXIE_TOOL} here."
            raise ToolRefusedError(msg)
        task = args.get("task")
        if not isinstance(task, str) or not task.strip() or len(task) > TASK_MAX:
            msg = f"task is required, at most {TASK_MAX} characters."
            raise ToolRefusedError(msg)
        if agents.rules is not None and not _callable(agents, agents.rules, slug):
            raise ToolRefusedError(MEMBER_CALL_DENIED.format(slug=slug))
        called = await self._start(caller, agents.tool_calls[slug], task.strip())
        waiting = self._waiting.setdefault(called.id, asyncio.get_running_loop().create_future())
        try:
            # It may have ended before the call began to wait.
            await self.state_changed(await self._sessions.get(called.id))
            ended = await waiting
        except BaseException:
            await self._close(called.id)
            raise
        finally:
            self._waiting.pop(called.id, None)
        report = await self._report(called.id)
        await self._close(called.id)
        return _outcome(slug, ended, report)

    async def _start(self, caller: Session, pixie_id: str, task: str) -> Session:
        try:
            pixie = await self._pixies.get(pixie_id)
            calling = await self._sessions.get(caller.id)
            folder = calling.worktree_path or calling.cwd
            assert folder is not None  # noqa: S101 (a chat whose agent runs has its folder)
            return await self._sessions.create_pixie_chat(
                pixie_id=pixie.id,
                cwd=folder,
                prompt=task,
                title=f"{pixie.name}, called by {calling.title}",
                model=run_model(pixie, self._defaults().model),
                effort=pixie.effort,
                permission_mode=pixie.permission_mode,
                attachment_ids=[],
                provider=pixie.provider,
                called_by=calling.id,
            )
        except NestError as error:
            raise ToolRefusedError(str(error)) from error

    async def _report(self, session_id: str) -> str:
        """The called session's last message of its own, its report."""
        events = await self._bus.session_events(session_id, 0, _NEWEST, _LAST_EVENTS)
        report = ""
        for event in events:
            payload = event.payload
            if event.type != types.SESSION_MESSAGE or payload.get("parent_tool_use_id"):
                continue
            blocks = payload.get("blocks")
            texts = [
                str(block.get("text", ""))
                for block in (blocks if isinstance(blocks, list) else [])
                if isinstance(block, dict) and block.get("type") == "text"
            ]
            if texts:
                report = "\n".join(texts)
        return report

    async def _close(self, session_id: str) -> None:
        """Stop the called session's agent; its transcript stays."""
        with suppress(NestError):
            await self._sessions.close(session_id, remove_worktree=False)


def _callable(agents: ChatAgents, rules: CallRules, slug: str) -> bool:
    """Whether some agent of the run may call the pixie: its main agent, or a leader of
    the pixie's team that runs as the run's own subagent (Claude's call guard checks which
    agent it is). A leader called with this tool calls its members from its own session.
    """
    return rules.may_call(None, slug) or any(
        slug in members
        for leader, members in rules.leaders.items()
        if leader not in agents.tool_calls
    )


def _outcome(slug: str, ended: Session | None, report: str) -> str:
    if ended is not None and ended.state is SessionState.IDLE:
        return report or f"@{slug} finished without a report."
    if ended is not None and ended.state is SessionState.FAILED:
        msg = f"@{slug} failed: {ended.last_error or 'its run failed'}"
        raise ToolRefusedError(msg)
    msg = f"@{slug} was stopped before it finished."
    raise ToolRefusedError(msg)
