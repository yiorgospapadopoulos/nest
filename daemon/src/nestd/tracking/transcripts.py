"""A subagent's own transcript, read from the session's stored events (B46).

The subagent's messages carry `parent_tool_use_id` set to the Agent call that started it.
A SendMessage that continues it starts a new part of its work, yet its messages keep that
first call's id, so they are told apart by order: each message belongs to the latest of
the calls made before it.
"""

from collections.abc import Sequence
from datetime import datetime

from pydantic import BaseModel, TypeAdapter

from nestd.events import types
from nestd.events.models import Event
from nestd.providers.base import AgentTask, MessageBlock, ToolResultBlock, ToolUseBlock

SEND_MESSAGE = "SendMessage"

_BLOCKS = TypeAdapter(list[MessageBlock])


class AgentMessage(BaseModel):
    event_id: int
    ts: datetime
    blocks: list[MessageBlock]


class AgentWork(BaseModel):
    """One call's part of a subagent's work: what it was asked, its own messages (its
    tool calls and results), and its report once there is one.
    """

    tool_use_id: str
    prompt: str | None
    messages: list[AgentMessage]
    report: str | None


def agent_work(events: Sequence[Event], parent: str, calls: Sequence[str]) -> list[AgentWork]:
    """The work of the subagent whose messages carry `parent`, for each of `calls` (its
    first call, then the SendMessage calls that continued it) the main agent made, in the
    order given.
    """
    wanted = set(calls)
    made: dict[str, ToolUseBlock] = {}
    results: dict[str, ToolResultBlock] = {}
    summaries: dict[str, str] = {}
    messages: dict[str, list[AgentMessage]] = {call: [] for call in calls}
    current: str | None = None
    for event in events:
        if event.type == types.SESSION_AGENT_TASK:
            task = AgentTask.model_validate(event.payload)
            if task.summary is not None and task.tool_use_id in wanted:
                summaries[task.tool_use_id] = task.summary
            continue
        if event.type != types.SESSION_MESSAGE:
            continue
        blocks = _BLOCKS.validate_python(event.payload["blocks"])
        owner = event.payload.get("parent_tool_use_id")
        if owner is None:
            for block in blocks:
                if isinstance(block, ToolUseBlock) and block.id in wanted:
                    made[block.id] = block
                    current = block.id
                elif isinstance(block, ToolResultBlock) and block.tool_use_id in wanted:
                    results[block.tool_use_id] = block
        elif owner == parent and current is not None:
            assert event.id is not None  # noqa: S101 (a stored event)
            messages[current].append(AgentMessage(event_id=event.id, ts=event.ts, blocks=blocks))
    return [
        AgentWork(
            tool_use_id=call,
            prompt=_prompt(made[call]),
            messages=messages[call],
            report=summaries.get(call) or _report(made[call], results.get(call)),
        )
        for call in calls
        if call in made
    ]


def _prompt(call: ToolUseBlock) -> str | None:
    value = call.input.get("message" if call.name == SEND_MESSAGE else "prompt")
    return value if isinstance(value, str) else None


def _report(call: ToolUseBlock, result: ToolResultBlock | None) -> str | None:
    """A foreground call's result is the subagent's report; a background call's only says
    it started, unless it failed to.
    """
    if result is None:
        return None
    background = call.name == SEND_MESSAGE or call.input.get("run_in_background") is True
    return result.content if result.is_error or not background else None
