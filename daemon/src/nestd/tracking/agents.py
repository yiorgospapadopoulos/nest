"""The main agent, the subagents it starts with the Agent tool, and its background commands.

A subagent's own messages carry `parent_tool_use_id` set to its Agent call's id. A
foreground subagent is done when that call's result arrives. A background one (started
with `run_in_background`, or moved there later) gets its result at once and keeps running;
it ends when the engine reports its task finished. Background Bash commands are followed
the same way. The main agent's status follows the session state.
"""

from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import IntEnum
from typing import Literal

from pydantic import JsonValue

from nestd.providers.base import AgentTask, MessageBlock, ToolResultBlock, ToolUseBlock
from nestd.tracking.models import (
    AgentStatus,
    AgentStep,
    BackgroundItem,
    BackgroundSummary,
    TrackedAgent,
)
from nestd.tracking.steps import short_arg, short_result

MAIN = "main"
# "Task" is the tool's name in older Claude Code versions.
AGENT_TOOLS = frozenset({"Agent", "Task"})
BASH_TOOL = "Bash"
# The engine's task type for a shell command.
LOCAL_BASH = "local_bash"
MAX_STEPS = 8
_RUNNING_STATES = frozenset({"starting", "running", "waiting"})
# Turn ends after which the agent run, and so its background work, goes on.
_RUN_STAYS = frozenset({"failed", "interrupted"})
_EARLIEST = datetime.min.replace(tzinfo=UTC)


class Change(IntEnum):
    NONE = 0
    ACTIVITY = 1  # a tool call or result; worth showing live, not worth storing
    LIFECYCLE = 2  # an agent or background command started or finished


@dataclass
class _Agent:
    """A subagent, the main agent, or a background command (kind "bash")."""

    id: str
    name: str
    description: str | None
    status: AgentStatus = "running"
    activity: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    steps: deque[AgentStep] = field(default_factory=lambda: deque[AgentStep](maxlen=MAX_STEPS))
    kind: Literal["agent", "bash"] = "agent"
    # Its tool call returns at once; its task's end is reported separately.
    background: bool = False

    def finish(self, status: AgentStatus, at: datetime) -> None:
        self.status = status
        self.activity = None
        self.finished_at = at


class AgentBoard:
    def __init__(self) -> None:
        self._agents: dict[str, _Agent] = {MAIN: _Agent(MAIN, MAIN, None)}
        # Background commands, by their Bash call's id.
        self._commands: dict[str, _Agent] = {}
        # The agent that made each tool call, by tool use id.
        self._callers: dict[str, str] = {}
        # Bash calls waiting for their result (command, description): one may move to the
        # background before it returns.
        self._bash: dict[str, tuple[str, str | None]] = {}
        # Tasks the engine started and has not finished, by task id.
        self._tasks: dict[str, AgentTask] = {}
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

    def background(self) -> BackgroundSummary:
        """Subagents and background commands, oldest first, with running and finished counts."""
        items = [
            BackgroundItem(
                id=a.id,
                kind=a.kind,
                name=a.name,
                description=a.description,
                status=a.status,
                started_at=a.started_at,
                finished_at=a.finished_at,
            )
            for a in [*self._agents.values(), *self._commands.values()]
            if a.id != MAIN
        ]
        items.sort(key=lambda item: item.started_at or _EARLIEST)
        running = sum(1 for item in items if item.status == "running")
        return BackgroundSummary(running=running, completed=len(items) - running, items=items)

    def started(self, at: datetime) -> None:
        self._agents[MAIN].started_at = at

    def stale(self) -> list[AgentTask]:
        """Background work still running reported stopped, as when its process is gone."""
        task_ids = {task.tool_use_id or task.task_id: task.task_id for task in self._tasks.values()}
        return [
            AgentTask(
                task_id=task_ids.get(agent.id, agent.id),
                phase="finished",
                tool_use_id=agent.id,
                status="stopped",
            )
            for agent in [*self._agents.values(), *self._commands.values()]
            if agent.background and agent.status == "running"
        ]

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

    def task(self, update: AgentTask, at: datetime) -> Change:
        if update.phase == "started":
            self._tasks[update.task_id] = update
            return self._to_background(update, at) if update.background else Change.NONE
        if update.phase == "backgrounded":
            task = self._tasks.get(update.task_id)
            return Change.NONE if task is None else self._to_background(task, at)
        return self._task_finished(update, at)

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
            # The turn was cut off: what it still runs will never report back. Background
            # work outlives a turn that ends normally, one the engine ended with an error
            # and one the user stopped, whose run stays open (D054, BUG-63, BUG-92): it
            # runs until the engine reports it finished, as approving counts it. A run
            # that ends reports its tasks stopped.
            kept = state in _RUN_STAYS
            for agent in [*self._agents.values(), *self._commands.values()]:
                if agent.status == "running" and not (kept and agent.background):
                    agent.finish("failed", at)
        return Change.LIFECYCLE

    def _tool_use(self, agent: _Agent, block: ToolUseBlock, at: datetime) -> Change:
        arg = short_arg(block.input, self.root)
        agent.steps.append(AgentStep(id=block.id, tool=block.name, arg=arg, result=None))
        agent.activity = f"{block.name} {arg}".strip()
        self._callers[block.id] = agent.id
        background = block.input.get("run_in_background") is True
        description = _text(block.input.get("description"))
        if block.name == BASH_TOOL:
            command = arg or "command"
            if not background:
                self._bash[block.id] = (command, description)
                return Change.ACTIVITY
            self._commands[block.id] = _command(block.id, command, description, at)
            return Change.LIFECYCLE
        if block.name not in AGENT_TOOLS:
            return Change.ACTIVITY
        self._agents[block.id] = _Agent(
            id=block.id,
            name=_text(block.input.get("subagent_type")) or "agent",
            description=description,
            started_at=at,
            background=background,
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
        self._bash.pop(block.tool_use_id, None)
        # A background call's result only says it started, unless it could not start.
        started = self._agents.get(block.tool_use_id) or self._commands.get(block.tool_use_id)
        if started is None or (started.background and not block.is_error):
            return Change.ACTIVITY
        started.finish("failed" if block.is_error else "done", at)
        return Change.LIFECYCLE

    def _to_background(self, task: AgentTask, at: datetime) -> Change:
        key = task.tool_use_id or task.task_id
        agent = self._agents.get(key)
        if agent is not None:
            if agent.background:
                return Change.NONE
            agent.background = True
            # Its call returned when it moved to the background; it is still at work.
            agent.status, agent.finished_at = "running", None
            return Change.LIFECYCLE
        if task.task_type != LOCAL_BASH or key in self._commands:
            return Change.NONE
        command, description = self._bash.pop(key, (task.description or "command", None))
        self._commands[key] = _command(key, command, description, at)
        return Change.LIFECYCLE

    def _task_finished(self, update: AgentTask, at: datetime) -> Change:
        task = self._tasks.pop(update.task_id, None)
        key = (task.tool_use_id if task else None) or update.tool_use_id or update.task_id
        agent = self._agents.get(key)
        # A foreground subagent ends with its tool call's result, as before.
        target = agent if agent is not None and agent.background else self._commands.get(key)
        status: AgentStatus = "done" if update.status == "completed" else "failed"
        if target is None or target.status == status:
            return Change.NONE
        target.finish(status, at)
        return Change.LIFECYCLE


def _command(call_id: str, command: str, description: str | None, at: datetime) -> _Agent:
    return _Agent(
        id=call_id,
        name=command,
        description=description,
        started_at=at,
        kind="bash",
        background=True,
    )


def _text(value: JsonValue) -> str | None:
    return value if isinstance(value, str) else None
