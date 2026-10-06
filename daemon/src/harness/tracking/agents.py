"""The main agent and the subagents it starts with the Agent tool.

A subagent's own messages carry `parent_tool_use_id` set to its Agent call's id; it is
done when that call's result arrives. The main agent's status follows the session state.
"""

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum

from harness.providers.base import MessageBlock, ToolResultBlock, ToolUseBlock
from harness.tracking.models import AgentStatus, AgentStep, TrackedAgent
from harness.tracking.steps import short_arg, short_result

MAIN = "main"
# "Task" is the tool's name in older Claude Code versions.
AGENT_TOOLS = frozenset({"Agent", "Task"})
MAX_STEPS = 8
_RUNNING_STATES = frozenset({"starting", "running", "waiting"})


class Change(IntEnum):
    NONE = 0
    ACTIVITY = 1  # a tool call or result; worth showing live, not worth storing
    LIFECYCLE = 2  # an agent started or finished


@dataclass
class _Agent:
    id: str
    name: str
    description: str | None
    status: AgentStatus = "running"
    activity: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    steps: deque[AgentStep] = field(default_factory=lambda: deque[AgentStep](maxlen=MAX_STEPS))

    def finish(self, status: AgentStatus, at: datetime) -> None:
        self.status = status
        self.activity = None
        self.finished_at = at


class AgentBoard:
    def __init__(self) -> None:
        self._agents: dict[str, _Agent] = {MAIN: _Agent(MAIN, MAIN, None)}
        # The agent that made each tool call, by tool use id.
        self._callers: dict[str, str] = {}
        # The session's working directory, for showing paths relative to it.
        self.root: str | None = None

    def snapshot(self) -> list[TrackedAgent]:
        return [
            TrackedAgent(
                id=a.id,
                name=a.name,
                description=a.description,
                status=a.status,
                activity=a.activity,
                started_at=a.started_at,
                finished_at=a.finished_at,
                steps=list(a.steps),
            )
            for a in self._agents.values()
        ]

    def started(self, at: datetime) -> None:
        self._agents[MAIN].started_at = at

    def message(self, blocks: list[MessageBlock], parent: str | None, at: datetime) -> Change:
        agent = self._agents.get(parent or MAIN)
        if agent is None:
            return Change.NONE  # a stream that started before we followed it
        change = Change.NONE
        for block in blocks:
            if isinstance(block, ToolUseBlock):
                change = max(change, self._tool_use(agent, block, at))
            elif isinstance(block, ToolResultBlock):
                change = max(change, self._tool_result(block, at))
        return change

    def state(self, state: str, at: datetime) -> Change:
        main = self._agents[MAIN]
        status: AgentStatus = (
            "running" if state in _RUNNING_STATES else "failed" if state == "failed" else "done"
        )
        if status == main.status:
            return Change.NONE
        if status == "running":
            main.status, main.finished_at = status, None
            return Change.LIFECYCLE
        main.finish(status, at)
        if state != "idle":
            # The turn was cut off; subagents still running will never report back.
            for agent in self._agents.values():
                if agent.status == "running":
                    agent.finish("failed", at)
        return Change.LIFECYCLE

    def _tool_use(self, agent: _Agent, block: ToolUseBlock, at: datetime) -> Change:
        arg = short_arg(block.input, self.root)
        agent.steps.append(AgentStep(id=block.id, tool=block.name, arg=arg, result=None))
        agent.activity = f"{block.name} {arg}".strip()
        self._callers[block.id] = agent.id
        if block.name not in AGENT_TOOLS:
            return Change.ACTIVITY
        name = block.input.get("subagent_type")
        description = block.input.get("description")
        self._agents[block.id] = _Agent(
            id=block.id,
            name=name if isinstance(name, str) else "agent",
            description=description if isinstance(description, str) else None,
            started_at=at,
        )
        return Change.LIFECYCLE

    def _tool_result(self, block: ToolResultBlock, at: datetime) -> Change:
        caller = self._agents.get(self._callers.pop(block.tool_use_id, ""))
        if caller is None:
            return Change.NONE
        result = short_result(block.content, block.is_error)
        for index, step in enumerate(caller.steps):
            if step.id == block.tool_use_id:
                caller.steps[index] = step.model_copy(update={"result": result})
        subagent = self._agents.get(block.tool_use_id)
        if subagent is None:
            return Change.ACTIVITY
        subagent.finish("failed" if block.is_error else "done", at)
        return Change.LIFECYCLE
