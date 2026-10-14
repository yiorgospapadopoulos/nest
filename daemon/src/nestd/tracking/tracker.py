"""One session's task list, agents and latest summary, built by applying its events."""

from pydantic import TypeAdapter

from nestd.events import types
from nestd.events.models import Event
from nestd.providers.base import (
    AgentTask,
    MessageBlock,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from nestd.tracking.agents import AgentBoard, Change
from nestd.tracking.tasks import TaskList

_BLOCKS = TypeAdapter(list[MessageBlock])


class SessionTracker:
    def __init__(self) -> None:
        self.tasks = TaskList()
        self.agents = AgentBoard()
        # The main agent's latest text, used as the summary of its work.
        self.summary: str | None = None
        self.last_event_id = 0

    def apply(self, event: Event) -> tuple[bool, Change]:
        """Apply one persisted event; whether the tasks changed, and how the agents did."""
        self.last_event_id = event.id or self.last_event_id
        payload = event.payload
        match event.type:
            case types.SESSION_CREATED:
                session = payload["session"]
                cwd = session.get("cwd") if isinstance(session, dict) else None
                self.agents.root = cwd if isinstance(cwd, str) else None
                self.agents.started(event.ts)
            case types.SESSION_WORKSPACE:
                self.agents.root = str(payload["path"])
            case types.SESSION_AGENT_TASK:
                return False, self.agents.task(AgentTask.model_validate(payload), event.ts)
            case types.SESSION_STATE:
                return False, self.agents.state(str(payload["state"]), event.ts)
            case types.SESSION_MESSAGE:
                parent = payload.get("parent_tool_use_id")
                return self._message(
                    _BLOCKS.validate_python(payload["blocks"]),
                    parent if isinstance(parent, str) else None,
                    event,
                )
            case _:
                pass
        return False, Change.NONE

    def _message(
        self, blocks: list[MessageBlock], parent: str | None, event: Event
    ) -> tuple[bool, Change]:
        tasks_changed = False
        if parent is None:
            for block in blocks:
                if isinstance(block, ToolUseBlock):
                    self.tasks.tool_use(block)
                elif isinstance(block, ToolResultBlock):
                    tasks_changed = self.tasks.tool_result(block) or tasks_changed
                elif isinstance(block, TextBlock) and block.text.strip():
                    self.summary = block.text
        return tasks_changed, self.agents.message(blocks, parent, event.ts)
