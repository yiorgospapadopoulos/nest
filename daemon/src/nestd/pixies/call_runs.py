"""Pixie calls with Nest's call_pixie tool (B91, B112), made to work as a Claude Code
subagent call.

Claude runs a called Claude pixie as its own subagent (B40), and Codex a Codex pixie as
its own (B112). Every other call, across engines or with an ACP engine, goes through the
call_pixie tool: the pixie works in a session of its own, in the caller's folder and
linked to it (`called_by`), with the prompt it would have as a subagent. The call is the
caller's subagent in every way a client sees:

- Its tool call is an agent row: the called session's messages, text, plan and tasks are
  relayed into the caller under the call's tool use id, as a subagent's carry it, and
  the call starts and finishes as an engine task (`AgentTask`, the called session's id as
  the task id), with its report as the summary.
- In the foreground the tool returns the report. With `run_in_background` it returns at
  once and the report reaches the caller when the call ends: written into its turn when
  one runs, else starting one, shown as a `pixie_result` line (B112).
- Calling the same pixie again in the chat continues its session while the pixie is
  defined as before and was not sent away; `fresh` starts it over (B46's rule).
- The called session's mode is the lower of the pixie's and the caller's; its approvals
  and questions are the caller's (sessions/prompts.py); it pauses at the usage limit as
  the caller would; its tokens count as the caller's subagent usage.
- The row's Stop stops the call; so does the caller's Stop of its turn for foreground
  calls, and closing or archiving the caller for all of them. A daemon restart
  interrupts running calls; a background one tells its caller so.

The call rules hold as for subagents (B70): the calling run's main agent calls solo pixies
and leaders, a leader its own members, which Claude's call guard checks per agent and this
tool for runs whose main agent is the only caller.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal
from uuid import uuid4

from pydantic import JsonValue

from nestd.config.models import AgentDefaults, PermissionMode
from nestd.errors import NestError
from nestd.events import types
from nestd.events.bus import EventBus
from nestd.pixies.call_models import BridgedCall, BridgedState
from nestd.pixies.call_store import BridgedCallStore
from nestd.pixies.calls import PixieCallLog
from nestd.pixies.models import Pixie, run_model
from nestd.pixies.store import PixieStore
from nestd.providers.base import (
    CALL_PIXIE_TOOL,
    AgentTask,
    AgentTool,
    CallRules,
    MessageBlock,
    TokenUsage,
    ToolRefusedError,
    ToolResultBlock,
    ToolUseBlock,
)
from nestd.providers.claude_tools import CALL_TOOL, MEMBER_CALL_DENIED
from nestd.sessions.manager import SessionManager
from nestd.sessions.models import Sender, Session, SessionState
from nestd.sessions.subagents import ChatAgents
from nestd.tracking.transcripts import ASYNC_LAUNCH

logger = logging.getLogger(__name__)

TASK_MAX = 20_000
# How long a call waits for its run to report the tool call it answers, which names it.
BIND_SECONDS = 2.0
# The pending tool calls kept per chat for calls that never ran, such as refused ones.
_PENDING_MAX = 50
# The states a called pixie's turn ends in, and those it works in.
FINISHED = frozenset(
    {SessionState.IDLE, SessionState.FAILED, SessionState.INTERRUPTED, SessionState.CLOSED}
)
WORKING = frozenset({SessionState.STARTING, SessionState.RUNNING, SessionState.WAITING})
_LAST_EVENTS = 400
_NEWEST = 2**62
# Events of a called session shown under its call, whose main agent's are the call's.
_UNDER_CALL = frozenset(
    {
        types.SESSION_MESSAGE,
        types.SESSION_PLAN,
        types.SESSION_THINKING_DELTA,
        types.SESSION_SUBAGENT_DELTA,
        types.SESSION_AGENT_TASK,
    }
)
DESCRIPTION = (
    "Call a pixie, a persistent agent set up in Nest, to do one part of the work. It works"
    " in this chat's folder in a session of its own and reports back. Give it the whole"
    " task: it does not see this conversation. Calling a pixie again in this chat continues"
    " its earlier session, with what it did there; set `fresh` to start it over. With"
    " `run_in_background` the call returns at once and the pixie's report arrives in this"
    " chat when it finishes: do not wait or check for it. Pixies you can call:\n{pixies}"
)
STARTED = (
    f"{ASYNC_LAUNCH} successfully: @{{slug}} is working in the background. Its report"
    " arrives in this chat when it finishes; do not call it again or check on it meanwhile."
)
FINISHED_REPORT = "Background call of @{slug} finished. Its report:\n\n{report}"
NO_REPORT = "@{slug} finished without a report."
FAILED_TEXT = "@{slug} failed: {error}"
STOPPED_TEXT = "@{slug} was stopped before it finished."
INTERRUPTED_TEXT = "@{slug} was interrupted, call it again to continue."
type TaskEnd = Literal["completed", "failed", "stopped"]
_STATUS: dict[BridgedState, TaskEnd] = {
    "done": "completed",
    "failed": "failed",
    "stopped": "stopped",
    "interrupted": "stopped",
}

# Records a called session's turn as its caller's subagent usage (B84).
type SubagentUsage = Callable[[str, str, TokenUsage], Awaitable[None]]


@dataclass(frozen=True)
class _Seen:
    """A call_pixie call a run reported, waiting for the tool's handler to take it."""

    tool_use_id: str
    slug: str
    task: str


@dataclass(eq=False)
class _Call:
    caller: str
    tool_use_id: str
    slug: str
    pixie_id: str
    called: str
    background: bool
    # The caller's run's pixies, for following the calls of a called leader.
    agents: ChatAgents
    # The newest stored event before the call's turn: its report comes after.
    after: int
    # Its turn began; a continued session is idle until then.
    started: bool
    ended: asyncio.Future[Session | None]
    stopped: bool = False
    paused: bool = False


class PixieCallRuns:
    """The call tool of each run with pixies to call this way, and their sessions."""

    def __init__(
        self,
        *,
        pixies: PixieStore,
        sessions: SessionManager,
        bus: EventBus,
        defaults: Callable[[], AgentDefaults],
        store: BridgedCallStore,
        log: PixieCallLog,
        usage: SubagentUsage | None = None,
        bind_seconds: float = BIND_SECONDS,
    ) -> None:
        """`defaults` gives the model of a Claude pixie without its own, read per call."""
        self._pixies = pixies
        self._sessions = sessions
        self._bus = bus
        self._defaults = defaults
        self._store = store
        self._log = log
        self._usage = usage
        self._bind_seconds = bind_seconds
        # Calls in progress, by called session.
        self._calls: dict[str, _Call] = {}
        # Tool calls of call_pixie that no handler took yet, by calling session.
        self._seen: dict[str, list[_Seen]] = {}
        self._arrived: dict[str, asyncio.Event] = {}
        self._background: set[asyncio.Task[None]] = set()

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
                "description": {
                    "type": "string",
                    "description": "A short (3-5 word) description of the task.",
                },
                "run_in_background": {
                    "type": "boolean",
                    "description": "Return at once; the report arrives when it finishes.",
                },
                "fresh": {
                    "type": "boolean",
                    "description": "Start the pixie over instead of continuing its session.",
                },
            },
            "required": ["pixie", "task"],
        }

        async def call(args: dict[str, JsonValue]) -> str:
            return await self._call(caller, agents, args)

        return (AgentTool(CALL_PIXIE_TOOL, DESCRIPTION.format(pixies=listing), schema, call),)

    async def recover(self) -> None:
        """On start: calls a previous process left running were interrupted with it. A
        background call's caller hears so, as it would have heard its report.
        """
        for call in await self._store.interrupt_all():
            if call.background and not call.delivered:
                await self._deliver_interrupted(call)

    async def shutdown(self) -> None:
        """After the agents stopped: background calls end with the daemon, unfinished, so
        its next start marks them interrupted.
        """
        running = list(self._background)
        for task in running:
            task.cancel()
        await asyncio.gather(*running, return_exceptions=True)
        self._calls.clear()

    # The run's events (CallBridge).

    async def message(
        self, session_id: str, blocks: list[MessageBlock], parent_tool_use_id: str | None
    ) -> None:
        self._note_calls(session_id, blocks)
        payload: dict[str, JsonValue] = {
            "blocks": [block.model_dump(mode="json") for block in blocks],
            "parent_tool_use_id": parent_tool_use_id,
        }
        await self.relay(session_id, types.SESSION_MESSAGE, payload)

    async def relay(self, session_id: str, event_type: str, payload: dict[str, JsonValue]) -> None:
        """A called session's event, shown under its call in the caller, and up the chain
        when the caller was called itself (a team's leader calling a member).
        """
        call = self._calls.get(session_id)
        if call is None:
            return
        if event_type == types.SESSION_DELTA:
            event_type = types.SESSION_SUBAGENT_DELTA
        elif event_type not in _UNDER_CALL:
            return
        parented = "parent_tool_use_id" in payload or event_type == types.SESSION_SUBAGENT_DELTA
        if parented and payload.get("parent_tool_use_id") is None:
            payload = {**payload, "parent_tool_use_id": call.tool_use_id}
        await self._emit(call.caller, event_type, payload, call.agents)

    async def turn_tokens(self, session_id: str, tokens: TokenUsage) -> bool:
        call = self._calls.get(session_id)
        if call is None or self._usage is None:
            return False
        top = call.caller
        while (above := self._calls.get(top)) is not None:
            top = above.caller
        await self._usage(top, f"call-{session_id}-{uuid4().hex}", tokens)
        return True

    async def stop(self, session_id: str, task_id: str) -> bool:
        call = next(
            (
                call
                for call in self._calls.values()
                if call.caller == session_id and task_id in (call.tool_use_id, call.called)
            ),
            None,
        )
        if call is None:
            return False
        await self._stop(call, "the call was stopped")
        return True

    async def released(self, session_id: str) -> None:
        await self._stop_calls(session_id, background=True)

    def calling(self, session_id: str) -> bool:
        return any(c.caller == session_id and not c.stopped for c in self._calls.values())

    # Session states (StateFollower).

    async def state_changed(self, session: Session) -> None:
        if self._sessions.stopping:
            # The daemon stops: its calls were interrupted, as its next start records.
            return
        call = self._calls.get(session.id)
        if call is not None:
            await self._called_state(call, session)
        if session.state is SessionState.CLOSED:
            await self._stop_calls(session.id, background=True)
            await self._close_called(session.id)
        elif session.state in (SessionState.INTERRUPTED, SessionState.FAILED):
            # The caller's turn was cut off: its foreground calls end with it, as its
            # subagents do; background ones go on (B112).
            await self._stop_calls(session.id, background=False)

    async def purged(self, session_id: str) -> None:
        call = self._calls.get(session_id)
        if call is not None and not call.ended.done():
            call.ended.set_result(None)
        await self._stop_calls(session_id, background=True)

    # The call.

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
        task = task.strip()
        # A called pixie's own calls run in the foreground, as a leader's calls of its
        # members do under Claude's call guard (B70).
        background = args.get("run_in_background") is True and caller.called_by is None
        tool_use_id = await self._bind(caller.id, slug, task)
        call = await self._open(
            caller, agents, slug, agents.tool_calls[slug], task, tool_use_id, background, args
        )
        if background:
            runner = asyncio.create_task(self._in_background(call))
            self._background.add(runner)
            runner.add_done_callback(self._background.discard)
            return STARTED.format(slug=slug)
        try:
            ended = await call.ended
        except BaseException:
            # The caller's tool call was cancelled: its turn was stopped or closed.
            await self._stop(call, "the call was cancelled")
            raise
        state, text = await self._finish(call, ended)
        if state != "done":
            raise ToolRefusedError(text)
        return text

    async def _open(
        self,
        caller: Session,
        agents: ChatAgents,
        slug: str,
        pixie_id: str,
        task: str,
        tool_use_id: str,
        background: bool,
        args: dict[str, JsonValue],
    ) -> _Call:
        """Start the called session, or continue the pixie's earlier one in this chat."""
        try:
            pixie = await self._pixies.get(pixie_id)
            calling = await self._sessions.get(caller.id)
            fingerprint = agents.pixie_fingerprint(slug)
            earlier = (
                None
                if args.get("fresh") is True
                else await self._continuable(caller.id, pixie.id, fingerprint)
            )
            mode = pixie.permission_mode
            after = await self._bus.last_id()
            if earlier is None:
                call = await self._create(calling, agents, pixie, task, tool_use_id, mode)
            else:
                call = self._track(calling, agents, pixie, earlier.called, tool_use_id, False)
                try:
                    await self._sessions.set_pixie_controls(call.called, {"permission_mode": mode})
                    await self._sessions.send(call.called, task, [])
                except BaseException:
                    self._calls.pop(call.called, None)
                    raise
        except NestError as error:
            raise ToolRefusedError(str(error)) from error
        call.background = background
        call.after = after
        await self._store.add(
            caller=caller.id,
            tool_use_id=tool_use_id,
            pixie_id=pixie.id,
            called=call.called,
            root=tool_use_id if earlier is None else earlier.root,
            fingerprint=fingerprint,
            background=background,
        )
        if earlier is not None:
            await self._log.continued(caller.id, tool_use_id, earlier.root)
        description = args.get("description")
        await self._task(
            call,
            AgentTask(
                task_id=call.called,
                phase="started",
                tool_use_id=tool_use_id,
                task_type="local_agent",
                description=description if isinstance(description, str) else None,
                background=background,
            ),
        )
        return call

    async def _create(
        self,
        calling: Session,
        agents: ChatAgents,
        pixie: Pixie,
        task: str,
        tool_use_id: str,
        mode: PermissionMode,
    ) -> _Call:
        folder = calling.worktree_path or calling.cwd
        assert folder is not None  # noqa: S101 (a chat whose agent runs has its folder)
        called = await self._sessions.create_pixie_chat(
            pixie_id=pixie.id,
            cwd=folder,
            prompt=task,
            title=f"{pixie.name}, called by {calling.title}",
            model=run_model(pixie, self._defaults().model),
            effort=pixie.effort,
            permission_mode=mode,
            attachment_ids=[],
            provider=pixie.provider,
            called_by=calling.id,
        )
        # Nothing ran since it was created: its first turn is only scheduled.
        return self._track(calling, agents, pixie, called.id, tool_use_id, started=True)

    def _track(
        self,
        calling: Session,
        agents: ChatAgents,
        pixie: Pixie,
        called: str,
        tool_use_id: str,
        started: bool,
    ) -> _Call:
        call = _Call(
            caller=calling.id,
            tool_use_id=tool_use_id,
            slug=pixie.slug,
            pixie_id=pixie.id,
            called=called,
            background=False,
            agents=agents,
            after=0,
            started=started,
            ended=asyncio.get_running_loop().create_future(),
        )
        self._calls[called] = call
        return call

    async def _continuable(
        self, caller: str, pixie_id: str, fingerprint: str
    ) -> BridgedCall | None:
        """The pixie's earlier session in this chat to continue: not sent away, defined
        as when it was first called, not busy with another call, and still open.
        """
        earlier = await self._store.latest(caller, pixie_id)
        if earlier is None or earlier.fingerprint != fingerprint or earlier.called in self._calls:
            return None
        try:
            session = await self._sessions.get(earlier.called)
        except NestError:
            return None
        if session.state is SessionState.CLOSED or session.archived_at is not None:
            return None
        return earlier

    async def _in_background(self, call: _Call) -> None:
        try:
            ended = await call.ended
            state, text = await self._finish(call, ended)
            await self._deliver(call.caller, call.tool_use_id, call.pixie_id, state, text)
        except Exception:
            logger.exception("the background call of @%s failed", call.slug)

    async def _finish(self, call: _Call, ended: Session | None) -> tuple[BridgedState, str]:
        """End the call: its state and what the caller gets, the report or why not."""
        self._calls.pop(call.called, None)
        state: BridgedState
        if (
            call.stopped
            or ended is None
            or ended.state
            in (
                SessionState.INTERRUPTED,
                SessionState.CLOSED,
            )
        ):
            state, text = "stopped", STOPPED_TEXT.format(slug=call.slug)
        elif ended.state is SessionState.FAILED:
            error = ended.last_error or "its run failed"
            state, text = "failed", FAILED_TEXT.format(slug=call.slug, error=error)
        else:
            report = await self._report(call)
            state, text = "done", report or NO_REPORT.format(slug=call.slug)
        if state != "done":
            await self._take_back_moves(call)
        await self._store.finish(call.caller, call.tool_use_id, state)
        await self._task(
            call,
            AgentTask(
                task_id=call.called,
                phase="finished",
                tool_use_id=call.tool_use_id,
                status=_STATUS[state],
                summary=text,
            ),
        )
        # Its engine run closes; the session stays, so the next call continues it.
        try:
            await self._sessions.close_idle_run(call.called)
        except NestError as error:
            logger.warning("closing the run of called pixie @%s failed (%s)", call.slug, error)
        return state, text

    async def _deliver(
        self, caller: str, tool_use_id: str, pixie_id: str, state: BridgedState, text: str
    ) -> None:
        """A background call's result into its caller's turn, or a turn of its own."""
        if state == "done":
            text = FINISHED_REPORT.format(slug=await self._slug(pixie_id), report=text)
        sender = Sender(
            origin="pixie_result",
            extra={"pixie_id": pixie_id, "tool_use_id": tool_use_id, "status": state},
        )
        try:
            await self._sessions.send(caller, text, [], sender=sender)
        except NestError as error:
            # The caller was closed or archived meanwhile, or cannot run now.
            logger.warning("the result of @%s did not reach its caller (%s)", pixie_id, error)
            return
        await self._store.delivered(caller, tool_use_id)

    async def _deliver_interrupted(self, call: BridgedCall) -> None:
        slug = await self._slug(call.pixie_id)
        await self._deliver(
            call.caller,
            call.tool_use_id,
            call.pixie_id,
            "interrupted",
            INTERRUPTED_TEXT.format(slug=slug),
        )

    async def _slug(self, pixie_id: str) -> str:
        try:
            return (await self._pixies.get(pixie_id)).slug
        except NestError:
            return pixie_id

    async def _called_state(self, call: _Call, session: Session) -> None:
        if session.state in WORKING:
            call.started = True
            if call.paused:
                call.paused = False
                await self._paused(call, False)
            return
        if session.state not in FINISHED or not (
            call.started or session.state is SessionState.CLOSED
        ):
            return
        if session.state is SessionState.IDLE and session.limit_pause is not None:
            # At the usage limit it waits for the reset, as its caller would (B112).
            if not call.paused:
                call.paused = True
                await self._paused(call, True)
            return
        if not call.ended.done():
            call.ended.set_result(session)

    async def _paused(self, call: _Call, paused: bool) -> None:
        await self._emit(
            call.caller,
            types.SESSION_AGENT_PAUSED,
            {"tool_use_id": call.tool_use_id, "paused": paused},
            call.agents,
        )

    async def _stop(self, call: _Call, reason: str) -> None:
        call.stopped = True
        try:
            await self._sessions.stop_call(call.called, reason)
        except NestError as error:
            logger.warning("stopping called pixie @%s failed (%s)", call.slug, error)
        await self._take_back_moves(call)
        if not call.ended.done():
            call.ended.set_result(None)

    async def _take_back_moves(self, call: _Call) -> None:
        try:
            await self._sessions.called_stopped(call.caller, call.called)
        except NestError as error:
            logger.warning("taking back what @%s recorded failed (%s)", call.slug, error)

    async def _stop_calls(self, caller: str, background: bool) -> None:
        for call in [c for c in self._calls.values() if c.caller == caller]:
            if background or not call.background:
                await self._stop(call, "its caller stopped")

    async def _close_called(self, caller: str) -> None:
        """A closed chat's pixies cannot be continued: their sessions close too."""
        for called in await self._store.called_sessions(caller):
            try:
                if (await self._sessions.get(called)).state is not SessionState.CLOSED:
                    await self._sessions.close(called, remove_worktree=False)
            except NestError as error:
                logger.warning("closing called session %s failed (%s)", called, error)

    async def _task(self, call: _Call, update: AgentTask) -> None:
        await self._emit(
            call.caller, types.SESSION_AGENT_TASK, update.model_dump(mode="json"), call.agents
        )

    async def _emit(
        self, session_id: str, event_type: str, payload: dict[str, JsonValue], agents: ChatAgents
    ) -> None:
        await self._sessions.agent_event(session_id, event_type, payload, agents)
        await self.relay(session_id, event_type, payload)

    def _note_calls(self, session_id: str, blocks: list[MessageBlock]) -> None:
        """Keep the run's call_pixie calls for their handlers, which learn their tool use
        id from them; a call that got its result without one (refused) is dropped.
        """
        seen = self._seen.setdefault(session_id, [])
        for block in blocks:
            if isinstance(block, ToolUseBlock) and block.name == CALL_TOOL:
                slug, task = block.input.get("pixie"), block.input.get("task")
                if isinstance(slug, str) and isinstance(task, str):
                    seen.append(_Seen(block.id, slug, task.strip()))
            elif isinstance(block, ToolResultBlock):
                seen[:] = [s for s in seen if s.tool_use_id != block.tool_use_id]
        del seen[:-_PENDING_MAX]
        arrived = self._arrived.get(session_id)
        if arrived is not None:
            arrived.set()

    async def _bind(self, session_id: str, slug: str, task: str) -> str:
        """The tool use id of the call the handler answers: the earliest such call the
        run reported. One it never reports gets an id of its own.
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._bind_seconds
        while True:
            seen = self._seen.get(session_id, [])
            found = next((s for s in seen if (s.slug, s.task) == (slug, task)), None)
            if found is not None:
                seen.remove(found)
                return found.tool_use_id
            remaining = deadline - loop.time()
            if remaining <= 0:
                return f"call-{uuid4().hex}"
            arrived = self._arrived.setdefault(session_id, asyncio.Event())
            arrived.clear()
            try:
                async with asyncio.timeout(remaining):
                    await arrived.wait()
            except TimeoutError:
                continue

    async def _report(self, call: _Call) -> str:
        """The called session's last message of its own in this call's turn: its report."""
        events = await self._bus.session_events(call.called, call.after, _NEWEST, _LAST_EVENTS)
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
