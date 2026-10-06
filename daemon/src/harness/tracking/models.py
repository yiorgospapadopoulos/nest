from datetime import datetime
from typing import Literal

from pydantic import BaseModel

type TaskStatus = Literal["pending", "in_progress", "completed", "deleted"]
type AgentStatus = Literal["running", "done", "failed"]

TASK_STATUSES: frozenset[str] = frozenset({"pending", "in_progress", "completed", "deleted"})


class TrackedTask(BaseModel):
    """One entry of the main agent's task list (TaskCreate and TaskUpdate calls)."""

    id: str
    subject: str
    description: str | None
    active_form: str | None
    status: TaskStatus


class AgentStep(BaseModel):
    id: str  # the tool use id
    tool: str
    arg: str
    result: str | None


class TrackedAgent(BaseModel):
    """The main agent ("main") or a subagent, identified by its Agent tool use id."""

    id: str
    name: str
    description: str | None
    status: AgentStatus
    # The latest tool call while running, such as "Edit src/x.ts".
    activity: str | None
    started_at: datetime | None
    finished_at: datetime | None
    steps: list[AgentStep]
