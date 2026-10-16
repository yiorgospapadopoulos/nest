"""The main agent's task list, from TaskCreate and TaskUpdate calls and their results.

A TaskCreate result reads `Task #<id> created successfully: <subject>`; that is where the
id comes from. Updates apply once their result shows they succeeded.

The visible list is the one the chat shows (D092): the user's next message clears it, since
Claude Code deletes a finished list and numbers the next one from #1 again. A task created
or updated after that shows again; a created id replaces the old task with that id.
"""

import re

from pydantic import JsonValue

from nestd.providers.base import ToolResultBlock, ToolUseBlock
from nestd.tracking.models import TASK_STATUSES, TrackedTask

TASK_CREATE = "TaskCreate"
TASK_UPDATE = "TaskUpdate"
_CREATED = re.compile(r"Task #(\w+) created successfully(?::\s*(.*))?")


class TaskList:
    def __init__(self) -> None:
        self._tasks: dict[str, TrackedTask] = {}
        self._visible: set[str] = set()
        # Calls waiting for their result, by tool use id.
        self._calls: dict[str, ToolUseBlock] = {}

    def snapshot(self) -> list[TrackedTask]:
        """The visible list in id order, so parallel creations list as the agent numbered them."""
        visible = (self._tasks[task_id] for task_id in self._visible)
        return sorted(visible, key=lambda t: (len(t.id), t.id))

    def clear(self) -> bool:
        """Hide every task, at the user's next message; whether the visible list changed."""
        changed = bool(self._visible)
        self._visible.clear()
        return changed

    def tool_use(self, block: ToolUseBlock) -> None:
        if block.name in (TASK_CREATE, TASK_UPDATE):
            self._calls[block.id] = block

    def tool_result(self, block: ToolResultBlock) -> bool:
        """Apply a call's result; whether the list changed."""
        call = self._calls.pop(block.tool_use_id, None)
        if call is None or block.is_error:
            return False
        if call.name == TASK_CREATE:
            return self._create(call.input, block.content)
        return self._update(call.input)

    def _create(self, tool_input: dict[str, JsonValue], result: str) -> bool:
        match = _CREATED.search(result)
        if match is None:
            return False
        self._visible.add(match.group(1))
        self._tasks[match.group(1)] = TrackedTask(
            id=match.group(1),
            subject=_text(tool_input.get("subject")) or (match.group(2) or "").strip(),
            description=_text(tool_input.get("description")),
            active_form=_text(tool_input.get("activeForm")),
            status="pending",
        )
        return True

    def _update(self, tool_input: dict[str, JsonValue]) -> bool:
        task = self._tasks.get(str(tool_input.get("taskId")))
        if task is None:
            return False
        changes: dict[str, str] = {}
        status = tool_input.get("status")
        if isinstance(status, str) and status in TASK_STATUSES:
            changes["status"] = status
        for field, key in (
            ("subject", "subject"),
            ("description", "description"),
            ("active_form", "activeForm"),
        ):
            value = _text(tool_input.get(key))
            if value is not None:
                changes[field] = value
        updated = task.model_copy(update=changes)
        self._tasks[task.id] = updated
        hidden = task.id not in self._visible
        self._visible.add(task.id)
        return hidden or updated != task


def _text(value: JsonValue) -> str | None:
    return value if isinstance(value, str) else None
