"""Translate Claude Agent SDK messages into provider-neutral sink calls."""

import json
import re
from datetime import datetime
from typing import Any, Literal, cast, get_args

from claude_agent_sdk import (
    TERMINAL_TASK_STATUSES,
    AssistantMessage,
    ContentBlock,
    ConversationResetMessage,
    HookEventMessage,
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

from nestd.config.models import PermissionMode
from nestd.providers import base
from nestd.providers.claude_commands import described_catalog, init_catalog
from nestd.providers.claude_thinking import ThinkingTimer

PERMISSION_MODES: frozenset[str] = frozenset(get_args(PermissionMode))
# How Claude Code wraps a local slash command's output in a user message.
_COMMAND_OUTPUT = re.compile(r"<local-command-(stdout|stderr)>(.*?)</local-command-\1>", re.DOTALL)


class TurnOutput:
    """Whether the current turn showed the user text: the agent's, a command's or a notice;
    and whether the engine's echo of the user message just sent is still to come.
    """

    def __init__(self) -> None:
        self.shown = False
        # The echo carries the message's id, the checkpoint its files restore to (IMP-02).
        self.awaiting_replay = False
        # Nest set the run's mode: the start-up report, made before that may have taken
        # effect, no longer says the mode the run works in (BUG-90).
        self.mode_set = False
        # Messages written into a running turn, by the uuid their echo carries, to their
        # Nest id (B59).
        self.steered: dict[str, str] = {}


async def translate(
    message: Message, sink: base.ProviderEventSink, thinking: ThinkingTimer, output: TurnOutput
) -> None:
    match message:
        case HookEventMessage(subtype="hook_response"):
            shown = hook_output(message)
            if shown is not None:
                await sink.hook(shown)
        case SystemMessage(subtype="init"):
            await sink.provider_session_id(str(message.data["session_id"]))
            await sink.connectors(mcp_servers(message.data.get("mcp_servers")))
            await _report_commands(init_catalog(message.data), sink)
            # The mode the run works in; Claude Code's own when it opened without one.
            if not output.mode_set:
                await _report_mode(message.data, sink)
        case SystemMessage(subtype="commands_changed"):
            await _report_commands(described_catalog(message.data), sink)
        case SystemMessage(subtype="status"):
            await _report_mode(message.data, sink)
        case SystemMessage(subtype="compact_boundary"):
            await _notice(sink, output, "compacted", "Conversation compacted")
        case SystemMessage(subtype="model_fallback"):
            await _notice(sink, output, "model_fallback", _fallback_text(message.data))
        case SystemMessage(subtype="api_retry"):
            error = message.data.get("error")
            reason = f" ({error})" if isinstance(error, str) and error else ""
            await _notice(sink, output, "api_retry", f"API error{reason}, retrying")
        case SystemMessage(subtype="local_command_output"):
            content = message.data.get("content")
            if isinstance(content, str) and content.strip():
                await _notice(sink, output, "command_output", content.strip())
        case ConversationResetMessage():
            await _notice(sink, output, "cleared", "Context cleared")
        case UserMessage(uuid=str() as uuid) if uuid in output.steered:
            # A message written into the turn was read: at a step, or as the next turn.
            thinking.mark()
            await sink.message_taken(output.steered.pop(uuid), uuid)
        case UserMessage() if _is_replay(message, output):
            # The user's own message, which the session already shows (IMP-02).
            output.awaiting_replay = False
            await sink.checkpoint(str(message.uuid))
        case UserMessage(content=str() as plain):
            # Plain user text is the user's own input, which the session already recorded,
            # or a local slash command's output, which only Claude Code has (PL-13).
            text = _command_output(plain)
            if text:
                await _notice(sink, output, "command_output", text)
        case AssistantMessage() | UserMessage():
            content = message.content if isinstance(message.content, list) else []
            blocks: list[base.MessageBlock] = [_block(block) for block in content]
            if isinstance(message, UserMessage):
                # Only tool results: text in a user message is the engine's own (a skill's
                # body, an interruption marker, a subagent's prompt), not Claude's (PL-09).
                blocks = [block for block in blocks if isinstance(block, base.ToolResultBlock)]
            if blocks:
                if message.parent_tool_use_id is None:
                    _time_thinking(blocks, thinking)
                    if isinstance(message, AssistantMessage) and any(
                        isinstance(block, base.TextBlock) for block in blocks
                    ):
                        output.shown = True
                await sink.message(blocks, message.parent_tool_use_id)
        case StreamEvent():
            if message.parent_tool_use_id is None:
                active = thinking.stream(message.event)
                if active is not None:
                    await sink.thinking(active)
            await _stream_delta(message, sink)
        case RateLimitEvent():
            usage = usage_info(message.rate_limit_info.raw)
            if usage is not None:
                await sink.usage(usage)
        case TaskStartedMessage() | TaskUpdatedMessage() | TaskNotificationMessage():
            for update in task_updates(message):
                await sink.task(update)
        case ResultMessage():
            thinking.reset()
            output.awaiting_replay = False
            # A local command that ran without the model may answer only here (PL-13).
            answer = (message.result or "").strip()
            if answer and not output.shown and not message.is_error and message.num_turns == 0:
                await sink.notice("command_output", answer)
            output.shown = False
            await sink.provider_session_id(message.session_id)
            await sink.result(
                base.ResultInfo(
                    is_error=message.is_error,
                    subtype=message.subtype,
                    duration_ms=message.duration_ms,
                    num_turns=message.num_turns,
                    errors=message.errors or [],
                    tokens=token_usage(message.usage or {}),
                )
            )
        case _:
            pass


async def _notice(
    sink: base.ProviderEventSink, output: TurnOutput, kind: base.NoticeKind, text: str
) -> None:
    output.shown = True
    await sink.notice(kind, text)


def _is_replay(message: UserMessage, output: TurnOutput) -> bool:
    """Whether `message` is the engine's echo of the user message just sent: the first
    user message after it from the main agent, with an id, that answers no tool and is not
    a local command's output. A message the engine injected (a task notification, a
    scheduled prompt) says where it came from (BUG-93).
    """
    if not output.awaiting_replay or message.uuid is None or message.parent_tool_use_id:
        return False
    if message.origin is not None and message.origin.get("kind") != "human":
        return False
    if isinstance(message.content, str):
        return not _command_output(message.content)
    return not any(isinstance(block, ToolResultBlock) for block in message.content)


async def _report_mode(data: dict[str, Any], sink: base.ProviderEventSink) -> None:
    mode = data.get("permissionMode")
    if mode in PERMISSION_MODES:
        await sink.permission_mode(mode)


def _command_output(content: str) -> str:
    """The text of a local command's output in `content`, else ""."""
    parts = (match.group(2).strip() for match in _COMMAND_OUTPUT.finditer(content))
    return "\n".join(part for part in parts if part)


def _fallback_text(data: dict[str, Any]) -> str:
    """The engine's own sentence, else the model it switched to."""
    content, model = data.get("content"), data.get("fallback_model")
    if isinstance(content, str) and content:
        return content
    return f"Switched to {model}" if isinstance(model, str) else "Switched to another model"


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
                # A status the SDK adds later still ends the task.
                status=_FINISHED.get(message.status, "stopped"),
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
        # The tool call that started each task, by its id.
        self._calls: dict[str, str] = {}

    def running(self, task_or_call_id: str) -> str | None:
        """The id of the running task named by its own id or its tool call's; else None."""
        task_id = self._calls.get(task_or_call_id, task_or_call_id)
        return task_id if task_id in self._running else None

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
            if message.tool_use_id is not None:
                self._calls[message.tool_use_id] = message.task_id
        elif isinstance(message, TaskNotificationMessage) or (
            isinstance(message, TaskUpdatedMessage) and message.status in TERMINAL_TASK_STATUSES
        ):
            self._running.discard(message.task_id)
        return len(self._running) if len(self._running) != before else None


def _time_thinking(blocks: list[base.MessageBlock], thinking: ThinkingTimer) -> None:
    """Give the main agent's thinking blocks their durations; later content counts from here."""
    for block in blocks:
        if isinstance(block, base.ThinkingBlock):
            block.duration_ms = thinking.took()
    thinking.mark()


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
            image_data=_result_images(block.content),
        )
    # The remaining block type: a server-side tool's result.
    return base.ToolResultBlock(tool_use_id=block.tool_use_id, content=json.dumps(block.content))


def _result_text(content: str | list[dict[str, Any]] | None) -> str:
    """The result's text; images it carries go separately, other content is named."""
    if content is None or isinstance(content, str):
        return content or ""
    return "\n".join(
        item["text"] if item.get("type") == "text" else f"[{item.get('type')}]"
        for item in content
        if _image(item) is None
    )


def _result_images(content: str | list[dict[str, Any]] | None) -> list[base.ImageData]:
    if not isinstance(content, list):
        return []
    return [image for item in content if (image := _image(item)) is not None]


def _image(item: dict[str, Any]) -> base.ImageData | None:
    """A base64 image block (B59), as a Read of an image or an MCP tool's image returns."""
    source = item.get("source")
    if item.get("type") != "image" or not isinstance(source, dict):
        return None
    fields = cast(dict[str, Any], source)
    media_type, data = fields.get("media_type"), fields.get("data")
    if isinstance(media_type, str) and isinstance(data, str):
        return base.ImageData(media_type=media_type, data=data)
    return None


async def _stream_delta(message: StreamEvent, sink: base.ProviderEventSink) -> None:
    """Text and thinking as they are written; a subagent's under its tool call (B59)."""
    event = message.event
    if event.get("type") != "content_block_delta":
        return
    delta = event.get("delta", {})
    parent = message.parent_tool_use_id
    match delta.get("type"):
        case "text_delta" if delta.get("text"):
            if parent is None:
                await sink.text_delta(delta["text"])
            else:
                await sink.subagent_delta(delta["text"], parent)
        case "thinking_delta" if delta.get("thinking"):
            await sink.thinking_delta(delta["thinking"], parent)
        case _:
            pass


_HOOK_OUTCOMES: dict[str, Literal["success", "error", "cancelled"]] = {
    "success": "success",
    "error": "error",
    "cancelled": "cancelled",
}


def hook_output(message: HookEventMessage) -> base.HookOutput | None:
    """What a finished hook has for the user, as Claude Code shows it: its JSON
    `systemMessage`, and a failure or block with why; None otherwise. Output a hook gives
    Claude (SessionStart and UserPromptSubmit context, plain stdout) is not shown.
    """
    data = message.data
    outcome = _HOOK_OUTCOMES.get(str(data.get("outcome")), "success")
    exit_code = data.get("exit_code")
    exit_code = exit_code if isinstance(exit_code, int) else None
    stdout = _string(data.get("stdout"))
    answer = _json_object(stdout)
    system_message = answer.get("systemMessage") if answer is not None else None
    if not isinstance(system_message, str) or not system_message.strip():
        system_message = None
    blocked = _block_reason(answer)
    shown = ""
    if blocked is not None:
        outcome, shown = "error", blocked
    elif outcome != "success" or exit_code not in (None, 0):
        if outcome == "success":
            outcome = "error"
        plain = "" if answer is not None else stdout
        shown = _string(data.get("stderr")) or plain or _string(data.get("output"))
    elif system_message is None:
        return None
    hook_id = data.get("hook_id")
    return base.HookOutput(
        hook_id=hook_id if isinstance(hook_id, str) else None,
        hook_name=_string(data.get("hook_name")) or message.hook_event_name,
        hook_event=message.hook_event_name,
        outcome=outcome,
        exit_code=exit_code,
        system_message=system_message.strip() if system_message else None,
        output=shown or None,
    )


def _block_reason(answer: dict[str, Any] | None) -> str | None:
    """Why a hook's JSON answer blocks the step or stops Claude, or None when it does not."""
    if answer is None:
        return None
    if answer.get("decision") == "block":
        return _string(answer.get("reason"))
    if answer.get("continue") is False:
        return _string(answer.get("stopReason"))
    return None


def _string(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _json_object(text: str) -> dict[str, Any] | None:
    """`text` as a JSON object, the form of a hook's structured answer; else None."""
    if not text.startswith("{"):
        return None
    try:
        return json.loads(text)
    except ValueError:
        return None


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
