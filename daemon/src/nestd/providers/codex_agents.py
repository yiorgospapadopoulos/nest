"""Codex's own subagents (its multi-agent tools) as Claude Code's subagents (B112).

A Codex agent spawns another with `spawn_agent` (a `collabAgentToolCall` item, tool
`spawnAgent`); the new agent is a thread of its own on the same connection, announced
with `thread/started` and its role (`agentRole`, the pixie's slug for a pixie). Nest shows
it as Claude Code shows a subagent, so clients, the agents board, pixie calls and Goals
need no engine branch:

- an `Agent` call in the caller's transcript, with `subagent_type` the role and the prompt,
  whose id is the new thread's id: the subagent's own messages, tool calls and plans carry
  it as their `parent_tool_use_id`, and its task is that thread (`AgentTask` started, then
  finished with its report as the summary);
- the call ends with the agent's report when its first turn ends while the caller is still
  at work (a foreground call). A caller whose turn ends first did not wait: the call moves
  to the background (`AgentTask` backgrounded, and a result saying it launched, with its
  agent id), and the report arrives with the task's end;
- continuing an agent (`send_input`, `followup_task`, `send_message`, or `resume_agent`
  with a message) is a `SendMessage` to its agent id, which ends with that agent's task.

The role and the caller's thread come from `thread/started`; should Codex not send it, a
`thread/read` asks. Until a thread is known its notifications wait, so its first messages
are never shown before its call.

The call rules of B70 hold as Claude's call guard holds them: a spawn of a pixie its caller
may not call is refused: its call fails with the reason, its turn is interrupted as soon as
it starts, and everything it asks is declined (`RunPermissions.refused`).
"""

import asyncio
import logging
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Literal

from pydantic import JsonValue

from nestd.providers.base import (
    AgentTask,
    CallRules,
    ProviderEventSink,
    ToolResultBlock,
    ToolUseBlock,
)
from nestd.providers.codex_items import items, obj, text
from nestd.providers.codex_rpc import JsonObject

logger = logging.getLogger(__name__)

AGENT_TOOL = "Agent"
SEND_MESSAGE = "SendMessage"
LOCAL_AGENT = "local_agent"
# Codex's role for an agent spawned without one.
DEFAULT_ROLE = "default"
COLLAB_ITEM = "collabAgentToolCall"
SPAWN = "spawnAgent"
# The result of a call whose caller went on without waiting; "Async agent launched" and the
# agent id are what pixie calls read from Claude's (B46).
LAUNCHED = (
    "Async agent launched; its report arrives when it finishes.\nagentId: {agent_id}"
    " (continue it with followup_task or send_input to this id)"
)
NO_AGENT = "Codex could not start the agent."
NO_REPORT = "The agent finished without a report."
STOPPED = "The agent was stopped."
MEMBER_REFUSED = (
    "{slug} is in a team and is called only by its leader. Hand the request to the team's"
    " leader instead; it calls its members."
)
PIXIE_REFUSED = (
    "Only a team's leader calls pixies, and only its own team's members. Spawn an agent"
    " without a pixie's role instead."
)
# The tools that continue an agent spawned earlier.
_CONTINUES = frozenset({"sendInput", "sendMessage", "followupTask", "resumeAgent"})
_ENDED: dict[str, Literal["completed", "failed", "stopped"]] = {
    "completed": "completed",
    "failed": "failed",
    "interrupted": "stopped",
}
# Notifications kept for a thread not known yet, at most.
_HELD = 500
# Seconds between reads of a spawned thread Codex cannot report yet.
_READ_RETRIES = (0.2, 0.5, 1.0, 2.0)

type Request = Callable[[str, JsonObject], Awaitable[JsonObject]]
type Replay = Callable[[str, JsonObject], Awaitable[None]]


@dataclass
class Subthread:
    """A subagent's thread: its id is its task's and its Agent call's."""

    id: str
    # The thread of the agent that spawned it.
    parent: str
    role: str | None
    # Why the call guard refused it (B70); None when it may work.
    refused: str | None = None
    turn_id: str | None = None
    running: bool = False
    # Its Agent call has its result: its first turn ended, or its caller went on.
    answered: bool = False
    # Its last turn's final message.
    report: str = ""
    # Reasoning items in progress, by id, to their start (ms).
    reasoning: dict[str, int] = field(default_factory=dict[str, int])


class CodexAgents:
    def __init__(self, sink: ProviderEventSink, rules: CallRules | None = None) -> None:
        """`rules` guards which agent calls which pixie (B70); None guards no calls."""
        self._sink = sink
        self._rules = rules
        # The run's own thread, once open.
        self.main: str | None = None
        self._threads: dict[str, Subthread] = {}
        # Spawns in progress by the thread that makes them, oldest first.
        self._spawning: dict[str, deque[JsonObject]] = {}
        # Prompts of finished spawns by the thread they started, until it is known.
        self._prompts: dict[str, str] = {}
        self._held: dict[str, list[tuple[str, JsonObject]]] = {}
        self._asked: set[str] = set()
        # Agents a message continues, perhaps spawned in an earlier run.
        self._earlier: set[str] = set()
        self._tasks: set[asyncio.Task[None]] = set()
        self._running = 0
        self._request: Request | None = None
        self._replay: Replay | None = None

    def connect(self, request: Request, replay: Replay) -> None:
        """`request` asks the app-server; `replay` handles a held notification."""
        self._request = request
        self._replay = replay

    def thread(self, thread_id: str) -> Subthread | None:
        return self._threads.get(thread_id)

    def caller(self, thread_id: str) -> str | None:
        """The role of the agent working in `thread_id`: None for the run's own agent."""
        thread = self._threads.get(thread_id)
        return None if thread is None else thread.role

    def hold(self, thread_id: str, method: str, params: JsonObject) -> None:
        """A notification of a thread not known yet, handled once it is."""
        held = self._held.setdefault(thread_id, [])
        if len(held) < _HELD:
            held.append((method, params))

    async def thread_started(self, thread: JsonObject) -> None:
        thread_id = text(thread.get("id"))
        spawn = _spawn_source(thread)
        if not thread_id or spawn is None:
            return  # the run's own thread, or one Codex runs for itself (a review)
        parent = text(thread.get("parentThreadId")) or text(spawn.get("parent_thread_id"))
        role = text(thread.get("agentRole")) or text(spawn.get("agent_role")) or None
        if parent and self._known(parent):
            await self._register(
                thread_id,
                parent,
                role,
                text(thread.get("preview")),
                announce=thread_id not in self._earlier,
            )

    async def collab_started(self, item: JsonObject) -> None:
        tool = item.get("tool")
        if tool == SPAWN:
            sender = text(item.get("senderThreadId")) or self.main or ""
            self._spawning.setdefault(sender, deque()).append(item)
        elif tool in _CONTINUES:
            # An agent of an earlier run, loaded again, is no new call.
            self._earlier.update(text(r) for r in items(item.get("receiverThreadIds")))

    async def collab_completed(self, item: JsonObject) -> None:
        sender = text(item.get("senderThreadId")) or self.main or ""
        tool = text(item.get("tool"))
        receivers = [text(r) for r in items(item.get("receiverThreadIds")) if text(r)]
        prompt = text(item.get("prompt"))
        if tool == SPAWN:
            self._drop_spawn(sender, text(item.get("id")))
            if not receivers:
                await self._failed_spawn(item, sender)
            for receiver in receivers:
                if receiver not in self._threads:
                    self._prompts[receiver] = prompt
                    self._ask(receiver, sender)
        elif tool in _CONTINUES and prompt:
            for index, receiver in enumerate(receivers):
                await self._continued(item, index, sender, receiver, prompt)

    async def turn_started(self, thread: Subthread, turn_id: str) -> None:
        thread.turn_id = turn_id or None
        if thread.refused is not None:
            self._interrupt(thread)
            return
        thread.running = True
        thread.report = ""
        await self._count()

    async def turn_completed(self, thread: Subthread, status: str, error: str) -> None:
        thread.turn_id = None
        thread.reasoning.clear()
        if thread.refused is not None or not thread.running:
            return
        thread.running = False
        ended = _ENDED.get(status, "failed")
        report = thread.report or error or (STOPPED if ended == "stopped" else NO_REPORT)
        if not thread.answered:
            thread.answered = True
            await self._sink.message(
                [
                    ToolResultBlock(
                        tool_use_id=thread.id, content=report, is_error=ended != "completed"
                    )
                ],
                self.parent_tool(thread.parent),
            )
        await self._sink.task(
            AgentTask(
                task_id=thread.id,
                phase="finished",
                tool_use_id=thread.id,
                status=ended,
                summary=thread.report or None,
            )
        )
        await self._count()
        await self.caller_went_on(thread.id)

    async def caller_went_on(self, sender: str) -> None:
        """The turn of the agent in `sender` ended: the agents it did not wait for go on in
        the background.
        """
        for thread in list(self._threads.values()):
            if thread.parent != sender or thread.answered or not thread.running:
                continue
            thread.answered = True
            await self._sink.task(AgentTask(task_id=thread.id, phase="backgrounded"))
            await self._sink.message(
                [
                    ToolResultBlock(
                        tool_use_id=thread.id, content=LAUNCHED.format(agent_id=thread.id)
                    )
                ],
                self.parent_tool(sender),
            )

    def parent_tool(self, thread_id: str) -> str | None:
        """The Agent call whose messages a thread's are: none for the run's own."""
        return thread_id if thread_id in self._threads else None

    async def stop(self, task_or_tool_use_id: str) -> bool:
        """Interrupt the subagent's turn; its end comes as its task's end."""
        thread = self._threads.get(task_or_tool_use_id)
        if thread is None or not thread.running or thread.turn_id is None:
            return False
        if self._request is None:
            return False
        await self._request("turn/interrupt", {"threadId": thread.id, "turnId": thread.turn_id})
        return True

    async def close(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    def _known(self, thread_id: str) -> bool:
        return thread_id == self.main or thread_id in self._threads

    async def _register(
        self, thread_id: str, parent: str, role: str | None, preview: str, announce: bool = True
    ) -> None:
        """`announce` is False for an agent called in an earlier run, whose call is there."""
        if thread_id in self._threads:
            return
        prompt = self._prompts.pop(thread_id, None)
        spawning = self._spawning.get(parent)
        if prompt is None and spawning and len(spawning) == 1:
            # One spawn in progress from its caller: this thread is its agent.
            prompt = text(spawning.popleft().get("prompt"))
        thread = Subthread(thread_id, parent, role, refused=self._refusal(parent, role))
        self._threads[thread_id] = thread
        if announce:
            await self._announce(thread, prompt or preview)
        else:
            thread.answered = True
        held = self._held.pop(thread_id, [])
        while held:
            method, params = held.pop(0)
            if self._replay is not None:
                await self._replay(method, params)
            held.extend(self._held.pop(thread_id, []))

    def _refusal(self, parent: str, role: str | None) -> str | None:
        rules = self._rules
        if rules is None or role is None or role not in rules.pixies:
            return None
        caller = self.caller(parent)
        if rules.may_call(caller, role):
            return None
        return PIXIE_REFUSED if caller is not None else MEMBER_REFUSED.format(slug=role)

    async def _announce(self, thread: Subthread, prompt: str) -> None:
        role = thread.role or DEFAULT_ROLE
        call: dict[str, JsonValue] = {
            "subagent_type": role,
            "description": role,
            "prompt": prompt,
            "run_in_background": False,
        }
        parent = self.parent_tool(thread.parent)
        await self._sink.message([ToolUseBlock(id=thread.id, name=AGENT_TOOL, input=call)], parent)
        if thread.refused is not None:
            thread.answered = True
            await self._sink.message(
                [ToolResultBlock(tool_use_id=thread.id, content=thread.refused, is_error=True)],
                parent,
            )
            return
        await self._sink.task(
            AgentTask(
                task_id=thread.id,
                phase="started",
                tool_use_id=thread.id,
                task_type=LOCAL_AGENT,
                description=role,
            )
        )

    async def _failed_spawn(self, item: JsonObject, sender: str) -> None:
        item_id = text(item.get("id"))
        states = [
            text(obj(state).get("message")) for state in obj(item.get("agentsStates")).values()
        ]
        reason = next((message for message in states if message), NO_AGENT)
        parent = self.parent_tool(sender)
        call: dict[str, JsonValue] = {
            "subagent_type": DEFAULT_ROLE,
            "description": DEFAULT_ROLE,
            "prompt": text(item.get("prompt")),
            "run_in_background": False,
        }
        await self._sink.message([ToolUseBlock(id=item_id, name=AGENT_TOOL, input=call)], parent)
        await self._sink.message(
            [ToolResultBlock(tool_use_id=item_id, content=reason, is_error=True)], parent
        )

    async def _continued(
        self, item: JsonObject, index: int, sender: str, receiver: str, prompt: str
    ) -> None:
        """A message to an agent spawned earlier, perhaps in an earlier run of the chat."""
        call_id = text(item.get("id")) + (f":{index}" if index else "")
        parent = self.parent_tool(sender)
        failed = item.get("status") == "failed"
        await self._sink.message(
            [
                ToolUseBlock(
                    id=call_id, name=SEND_MESSAGE, input={"to": receiver, "message": prompt}
                )
            ],
            parent,
        )
        await self._sink.message(
            [
                ToolResultBlock(
                    tool_use_id=call_id,
                    content='{"success": false}' if failed else '{"success": true}',
                    is_error=failed,
                )
            ],
            parent,
        )
        thread = self._threads.get(receiver)
        if thread is None:
            self._ask(receiver, sender, announce=False)
        else:
            # Its call was answered long ago; this message's answer is its task's end.
            thread.answered = True

    def _ask(self, thread_id: str, sender: str, announce: bool = True) -> None:
        """Ask Codex about a thread it did not announce, in the background: a request
        cannot wait for its answer on the connection's reader.
        """
        if thread_id in self._asked or self._request is None:
            return
        self._asked.add(thread_id)
        task = asyncio.create_task(self._read(thread_id, sender, announce))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _read(self, thread_id: str, sender: str, announce: bool) -> None:
        assert self._request is not None  # noqa: S101 (asked only when connected)
        response: JsonObject = {}
        # A thread just spawned may not be readable yet (live check 2026-10-27: the first
        # read failed and the pixie showed as "default"), so it is asked again a few times.
        for delay in (*_READ_RETRIES, None):
            try:
                response = await self._request("thread/read", {"threadId": thread_id})
                break
            except Exception as error:
                if delay is None:
                    logger.warning(
                        "Codex did not say which agent thread %s is: %s", thread_id, error
                    )
                else:
                    await asyncio.sleep(delay)
        thread = obj(response.get("thread"))
        role = text(thread.get("agentRole")) or None
        parent = text(thread.get("parentThreadId")) or sender
        await self._register(thread_id, parent, role, text(thread.get("preview")), announce)

    def _drop_spawn(self, sender: str, item_id: str) -> None:
        spawning = self._spawning.get(sender)
        if spawning is None:
            return
        for entry in list(spawning):
            if text(entry.get("id")) == item_id:
                spawning.remove(entry)

    def _interrupt(self, thread: Subthread) -> None:
        if self._request is None or thread.turn_id is None:
            return
        request = self._request
        params: JsonObject = {"threadId": thread.id, "turnId": thread.turn_id}

        async def interrupt() -> None:
            try:
                await request("turn/interrupt", params)
            except Exception:
                logger.warning("Codex did not stop the refused agent thread %s", thread.id)

        task = asyncio.create_task(interrupt())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _count(self) -> None:
        running = sum(1 for thread in self._threads.values() if thread.running)
        if running != self._running:
            self._running = running
            await self._sink.background_tasks(running)


def _spawn_source(thread: JsonObject) -> JsonObject | None:
    """A thread an agent spawned: its source's `thread_spawn`, else None. A thread Codex
    runs for itself (a review, a compaction) is no subagent.
    """
    source = thread.get("source")
    if isinstance(source, dict):
        sub = source.get("subAgent")
        if isinstance(sub, dict) and isinstance(sub.get("thread_spawn"), dict):
            return obj(sub.get("thread_spawn"))
        if sub is not None:
            return None
    if text(thread.get("parentThreadId")) and (
        text(thread.get("agentRole")) or text(thread.get("agentNickname"))
    ):
        return {}
    return None
