"""Translate Claude Agent SDK messages into provider-neutral sink calls."""

import json
from datetime import datetime
from typing import Any, Literal, cast

from claude_agent_sdk import (
    TERMINAL_TASK_STATUSES,
    AssistantMessage,
    ContentBlock,
    Message,
    RateLimitEvent,
    ResultMessage,
    ServerToolUseBlock,
    StreamEvent,
    SystemMessage,
    TaskNotificationMessage,
    TaskStartedMessage,
    TaskUpdatedMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from harness.providers import base
from harness.providers.claude_commands import described_catalog, init_catalog


async def translate(message: Message, sink: base.ProviderEventSink) -> None:
    match message:
        case SystemMessage(subtype="init"):
            await sink.provider_session_id(str(message.data["session_id"]))
            await sink.connectors(mcp_servers(message.data.get("mcp_servers")))
            await _report_commands(init_catalog(message.data), sink)
        case SystemMessage(subtype="commands_changed"):
            await _report_commands(described_catalog(message.data), sink)
        case AssistantMessage() | UserMessage():
            # Plain-text user content is the engine echoing input the session already recorded.
            content = message.content if isinstance(message.content, list) else []
            if content:
                await sink.message([_block(block) for block in content], message.parent_tool_use_id)
        case StreamEvent():
            text = _text_delta(message)
            if text is not None:
                await sink.text_delta(text)
        case RateLimitEvent():
            usage = usage_info(message.rate_limit_info.raw)
            if usage is not None:
                await sink.usage(usage)
        case TaskStartedMessage() | TaskUpdatedMessage() | TaskNotificationMessage():
            for update in task_updates(message):
                await sink.task(update)
        case ResultMessage():
            await sink.provider_session_id(message.session_id)
            await sink.result(
                base.ResultInfo(
                    is_error=message.is_error,
                    subtype=message.subtype,
                    duration_ms=message.duration_ms,
                    num_turns=message.num_turns,
                    cost_usd=message.total_cost_usd,
                    errors=message.errors or [],
                    tokens=token_usage(message.usage or {}),
                )
            )
        case _:
            pass


async def _report_commands(
    catalog: base.CommandCatalog | None, sink: base.ProviderEventSink
) -> None:
    if catalog is not None:
        await sink.commands(catalog)


_FINISHED: dict[str, Literal["completed", "failed", "stopped"]] = {
    "completed": "completed",
    "failed": "failed",
    "stopped": "stopped",
    "killed": "stopped",  # task_updated's raw form of stopped
}


def task_updates(
    message: TaskStartedMessage | TaskUpdatedMessage | TaskNotificationMessage,
) -> list[base.AgentTask]:
    """What a task lifecycle message says; a task_updated patch can say two things at once."""
    if isinstance(message, TaskStartedMessage):
        return [
            base.AgentTask(
                task_id=message.task_id,
                phase="started",
                tool_use_id=message.tool_use_id,
                task_type=message.task_type,
                description=message.description,
                background=message.data.get("is_backgrounded") is True,
            )
        ]
    if isinstance(message, TaskNotificationMessage):
        return [
            base.AgentTask(
                task_id=message.task_id,
                phase="finished",
                tool_use_id=message.tool_use_id,
                status=_FINISHED[message.status],
            )
        ]
    updates: list[base.AgentTask] = []
    if message.patch.get("is_backgrounded") is True:
        updates.append(base.AgentTask(task_id=message.task_id, phase="backgrounded"))
    status = _FINISHED.get(message.status or "")
    if status is not None:
        updates.append(base.AgentTask(task_id=message.task_id, phase="finished", status=status))
    return updates


class BackgroundTasks:
    """Tracks the agent's running tasks; a finish can arrive as a notification or an update."""

    def __init__(self) -> None:
        self._running: set[str] = set()

    def abandon(self) -> list[base.AgentTask]:
        """The run ended: every task still running is stopped with it."""
        stopped = [
            base.AgentTask(task_id=task_id, phase="finished", status="stopped")
            for task_id in sorted(self._running)
        ]
        self._running.clear()
        return stopped

    def update(self, message: Message) -> int | None:
        """The new number of running tasks, or None if `message` did not change it."""
        before = len(self._running)
        if isinstance(message, TaskStartedMessage):
            self._running.add(message.task_id)
        elif isinstance(message, TaskNotificationMessage) or (
            isinstance(message, TaskUpdatedMessage) and message.status in TERMINAL_TASK_STATUSES
        ):
            self._running.discard(message.task_id)
        return len(self._running) if len(self._running) != before else None


def _block(block: ContentBlock) -> base.MessageBlock:
    if isinstance(block, TextBlock):
        return base.TextBlock(text=block.text)
    if isinstance(block, ThinkingBlock):
        return base.ThinkingBlock(text=block.thinking)
    if isinstance(block, ToolUseBlock | ServerToolUseBlock):
        return base.ToolUseBlock(id=block.id, name=block.name, input=block.input)
    if isinstance(block, ToolResultBlock):
        return base.ToolResultBlock(
            tool_use_id=block.tool_use_id,
            content=_result_text(block.content),
            is_error=bool(block.is_error),
        )
    # The remaining block type: a server-side tool's result.
    return base.ToolResultBlock(tool_use_id=block.tool_use_id, content=json.dumps(block.content))


def _result_text(content: str | list[dict[str, Any]] | None) -> str:
    if content is None or isinstance(content, str):
        return content or ""
    return "\n".join(
        item["text"] if item.get("type") == "text" else f"[{item.get('type')}]" for item in content
    )


def _text_delta(message: StreamEvent) -> str | None:
    """Token-level text of the main agent; subagent and thinking deltas are skipped."""
    event = message.event
    if message.parent_tool_use_id is not None or event.get("type") != "content_block_delta":
        return None
    delta = event.get("delta", {})
    return delta.get("text") if delta.get("type") == "text_delta" else None


def mcp_servers(raw: object) -> list[base.McpServer]:
    """Entries with a string name and status (and error, if any); others are skipped."""
    entries = cast("list[object]", raw) if isinstance(raw, list) else []
    servers: list[base.McpServer] = []
    for entry in entries:
        try:
            server = _Server.model_validate(entry)
        except ValidationError:
            continue
        servers.append(base.McpServer(server.name, server.status, server.error))
    return servers


def token_usage(usage: dict[str, Any]) -> base.TokenUsage:
    """The four token counts; missing or non-integer values count as zero."""
    counts = {
        name: value
        for name, value in usage.items()
        if name in base.TokenUsage.model_fields and isinstance(value, int)
    }
    return base.TokenUsage.model_validate(counts)


class _Server(BaseModel):
    model_config = ConfigDict(strict=True)

    name: str
    status: str
    error: str | None = None


class _Window(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    utilization: float
    resets_at: datetime | None = Field(default=None, alias="resetsAt")


class _Windows(BaseModel):
    five_hour: _Window | None = None
    seven_day: _Window | None = None


def usage_info(raw: dict[str, Any]) -> base.UsageInfo | None:
    """Five-hour and seven-day windows from the CLI's `unifiedWindows`, when present."""
    try:
        windows = _Windows.model_validate(raw.get("unifiedWindows"))
    except ValidationError:
        return None
    if windows.five_hour is None and windows.seven_day is None:
        return None
    return base.UsageInfo(
        five_hour=_window(windows.five_hour), seven_day=_window(windows.seven_day)
    )


def _window(window: _Window | None) -> base.UsageWindow | None:
    if window is None:
        return None
    return base.UsageWindow(utilization=window.utilization, resets_at=window.resets_at)
