"""One ACP session's `session/update` notifications as the sink's calls (B107).

Text and thinking stream as deltas; each message ends as a block when something else
comes (another message, a tool call, the turn's end). Tool calls get the names Claude Code
uses for the same work, so clients draw them as they draw Claude's: a shell command is
`Bash`, an edit `Edit` (or `Write` for a whole new file) with its old and new text, a read
`Read`, a search `Grep`, a fetch `WebFetch` (or `WebSearch`), one of Nest's own MCP tools
`mcp__<server>__<tool>`, and anything else the engine's title for it. A call is drawn once
its input is known: when it runs, ends or asks permission (OpenCode first announces a call
with no input). Its result comes when it completes or fails.

The engine's own plan (`plan`, the whole list each time) is the main agent's task list, as
Claude Code's TaskCreate and TaskUpdate keep it (B112).

The turn ends with the answer to its `session/prompt`: the stop reason and the tokens it
used. A session reopened with `session/load` replays its history first; Nest has the
transcript, so the replay is dropped (`replaying`).
"""

import re
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import ClassVar, Literal

from pydantic import JsonValue

from nestd.providers.acp_rpc import JsonObject
from nestd.providers.base import (
    CommandCatalog,
    ContextUsage,
    PlanStep,
    ProviderEventSink,
    ResultInfo,
    SlashCommand,
    TextBlock,
    ThinkingBlock,
    TokenUsage,
    ToolResultBlock,
    ToolUseBlock,
)
from nestd.providers.codex_items import items, obj, text

# Nest's own MCP servers of a run by name, with their tools' names.
type NestTools = Mapping[str, frozenset[str]]

# The kinds of call that change files, judged by their paths.
EDIT_KINDS = frozenset({"edit", "delete", "move"})
# The kinds of call that only look.
READ_KINDS = frozenset({"read", "search", "fetch", "think"})
# The ones of them judged by the paths they look at: allowed inside the chat's folders.
LOOK_KINDS = frozenset({"read", "search"})
# The engine's own tools with a kind Nest draws as Claude Code's.
_KNOWN_KINDS = READ_KINDS | EDIT_KINDS | {"execute"}
_RUNNING = frozenset({"in_progress", "completed", "failed"})
_ENDED = frozenset({"completed", "failed"})
# Input keys, lowercased without separators, that hold a file path or a list of them.
_PATH_KEYS = frozenset(
    {
        "path",
        "paths",
        "filepath",
        "filepaths",
        "file",
        "files",
        "filename",
        "absolutepath",
        "dirpath",
        "directory",
        "dir",
        "notebookpath",
        "source",
        "destination",
        "newpath",
        "targetpath",
        "movepath",
    }
)
UNFINISHED = "The turn ended before this tool call finished."
# ACP's plan entry statuses are Nest's; anything else is taken as not started.
_PLAN_STATUSES: dict[str, Literal["pending", "in_progress", "completed"]] = {
    "pending": "pending",
    "in_progress": "in_progress",
    "completed": "completed",
}
_STOPS: dict[str, tuple[str, bool, str | None]] = {
    "end_turn": ("success", False, None),
    "cancelled": ("cancelled", False, None),
    "max_tokens": ("max_tokens", True, "The reply reached the model's token limit."),
    "max_turn_requests": ("max_turns", True, "The turn reached the engine's step limit."),
    "refusal": ("refusal", True, "The model refused to go on."),
}


@dataclass
class ToolCall:
    """What the engine said about one tool call so far."""

    id: str
    kind: str = ""
    title: str = ""
    status: str = ""
    raw_input: JsonObject = field(default_factory=dict[str, JsonValue])
    content: list[JsonValue] = field(default_factory=list[JsonValue])
    locations: list[str] = field(default_factory=list[str])
    raw_output: JsonValue = None
    shown: bool = False
    # Why Nest rejected the call itself, which its result shows instead of the engine's
    # words (the engine only hears "rejected").
    refused: str | None = None

    def update(self, fields: JsonObject) -> None:
        """ACP updates carry only what changed; a list replaces the earlier one. A kind
        Nest draws as Claude Code's is kept over a vaguer one a later message gives (a
        permission request's call can say less than the call itself).
        """
        kind = text(fields.get("kind"))
        if kind and (kind in _KNOWN_KINDS or self.kind not in _KNOWN_KINDS):
            self.kind = kind
        self.title = text(fields.get("title")) or self.title
        self.status = text(fields.get("status")) or self.status
        self.raw_input |= obj(fields.get("rawInput"))
        if content := items(fields.get("content")):
            self.content = content
        locations = [text(obj(entry).get("path")) for entry in items(fields.get("locations"))]
        if any(locations):
            self.locations = [path for path in locations if path]
        if "rawOutput" in fields:
            self.raw_output = fields["rawOutput"]

    def diffs(self) -> list[JsonObject]:
        return [obj(part) for part in self.content if obj(part).get("type") == "diff"]


def command_text(call: ToolCall) -> str:
    """The command a shell call runs: from its input, else its title (Gemini's)."""
    raw = call.raw_input
    return text(raw.get("command")) or text(raw.get("cmd")) or call.title


def paths(call: ToolCall) -> list[str]:
    """Every file path the call names, in its input, its diffs and its locations."""
    found: list[str] = []
    for key, value in call.raw_input.items():
        if _letters(key) not in _PATH_KEYS:
            continue
        if isinstance(value, str) and value:
            found.append(value)
        elif isinstance(value, list):
            found += [entry for entry in value if isinstance(entry, str) and entry]
    found += [path for diff in call.diffs() if (path := text(diff.get("path")))]
    found += call.locations
    return list(dict.fromkeys(found))


def tool_use(call: ToolCall, nest: NestTools) -> tuple[str, dict[str, JsonValue]]:
    """The call's name and input as Claude Code would show the same work."""
    raw = call.raw_input
    own = nest_tool(call, nest)
    if own is not None:
        return own, dict(raw)
    if shell_call(call):
        return "Bash", {"command": command_text(call)}
    if call.kind == "edit":
        return _edit(call)
    if call.kind == "read":
        found = paths(call)
        return "Read", {"file_path": found[0] if found else call.title}
    if call.kind == "search":
        pattern = text(raw.get("pattern")) or text(raw.get("query")) or call.title
        search: dict[str, JsonValue] = {"pattern": pattern}
        if where := text(raw.get("path")):
            search["path"] = where
        return "Grep", search
    if call.kind == "fetch":
        if url := text(raw.get("url")):
            return "WebFetch", {"url": url}
        if query := text(raw.get("query")):
            return "WebSearch", {"query": query}
        return "WebFetch", {"url": call.title}
    return title_name(call.title) or call.kind or "Tool", dict(raw)


def nest_tool(call: ToolCall, nest: NestTools) -> str | None:
    """`mcp__<server>__<tool>` when the call is one of Nest's own MCP tools, which OpenCode
    titles `<server>_<tool>`.

    Nest's tools pass without asking, so the whole title must be one name with the server
    in it, at most followed by plain arguments: a call that carries a command never
    counts, nor does a bare tool name another server could share (Gemini's `<tool>(...)`
    titles are therefore asked), nor anything after the arguments.
    """
    if call.kind in _KNOWN_KINDS or command_in(call.raw_input):
        return None
    found = _TOOL_TITLE.fullmatch(call.title.strip())
    if found is None:
        return None
    name = found.group("name")
    for server, tools in nest.items():
        for tool in tools:
            if name in (f"{server}_{tool}", f"mcp_{server}_{tool}", f"mcp__{server}__{tool}"):
                return f"mcp__{server}__{tool}"
    return None


# A tool's title: one name, optionally with arguments that hold no parentheses.
_TOOL_TITLE = re.compile(r"(?P<name>[A-Za-z0-9_-]+)(?:\([^()]*\))?")


def command_in(raw: Mapping[str, JsonValue]) -> bool:
    return bool(text(raw.get("command")) or text(raw.get("cmd")))


def title_name(title: str) -> str:
    """A title without the arguments some engines add: `echo(text: hi)` is `echo`."""
    return title.split("(", 1)[0].strip()


def shell_call(call: ToolCall) -> bool:
    """A shell command: its kind says so, or a call without a kind Nest knows has a
    command in its input (OpenCode 1.19 can ask about a command without the kind).
    """
    if call.kind == "execute":
        return True
    raw = call.raw_input
    command = text(raw.get("command")) or text(raw.get("cmd"))
    return unknown_kind(call) and bool(command)


def unknown_kind(call: ToolCall) -> bool:
    """Whether the call is not one of the kinds of the engine's own tools (an MCP tool)."""
    return call.kind not in _KNOWN_KINDS


def _edit(call: ToolCall) -> tuple[str, dict[str, JsonValue]]:
    raw = call.raw_input
    diffs = call.diffs()
    diff = diffs[0] if diffs else {}
    found = paths(call)
    path = found[0] if found else text(diff.get("path"))
    shown: dict[str, JsonValue]
    old, new = raw.get("oldString"), raw.get("newString")
    if isinstance(old, str) and isinstance(new, str):
        shown = {"file_path": path, "old_string": old, "new_string": new}
    elif isinstance(content := raw.get("content"), str):
        return "Write", {"file_path": path, "content": content}
    elif diff:
        before, after = text(diff.get("oldText")), text(diff.get("newText"))
        if not before:
            return "Write", {"file_path": path, "content": after}
        shown = {"file_path": path, "old_string": before, "new_string": after}
    else:
        shown = {"file_path": path, "old_string": "", "new_string": ""}
    if unified := text(raw.get("diff")):
        shown["diff"] = unified
    return "Edit", shown


def _result(call: ToolCall) -> ToolResultBlock:
    texts = [
        text(obj(obj(part).get("content")).get("text"))
        for part in call.content
        if obj(part).get("type") == "content"
    ]
    body = "\n".join(t for t in texts if t)
    output = obj(call.raw_output)
    failed = call.status == "failed"
    if call.refused is not None:
        return ToolResultBlock(tool_use_id=call.id, content=call.refused, is_error=True)
    if not body:
        body = text(output.get("error")) if failed else text(output.get("output"))
    if not body and call.diffs():
        body = "Done"
    return ToolResultBlock(tool_use_id=call.id, content=body, is_error=failed)


def tokens(usage: JsonObject) -> TokenUsage:
    """A prompt's usage: input without the cached part, output with the thinking."""

    def count(name: str) -> int:
        value = usage.get(name)
        return value if isinstance(value, int) else 0

    return TokenUsage(
        input_tokens=count("inputTokens"),
        output_tokens=count("outputTokens") + count("thoughtTokens"),
        cache_read_input_tokens=count("cachedReadTokens"),
        cache_creation_input_tokens=count("cachedWriteTokens"),
    )


class AcpStream:
    def __init__(self, sink: ProviderEventSink, nest: NestTools) -> None:
        self._sink = sink
        # Nest's own MCP servers, known once the run has chosen them.
        self.nest = nest
        self.session_id: str | None = None
        # True while `session/load` replays history Nest already has.
        self.replaying = False
        self._calls: dict[str, ToolCall] = {}
        self._text: list[str] = []
        self._text_id = ""
        self._thought: list[str] = []
        self._thought_id = ""
        self._thought_started = 0.0
        self._context: ContextUsage | None = None

    def context_usage(self) -> ContextUsage | None:
        return self._context

    async def handle(self, method: str, params: JsonObject) -> None:
        if method != "session/update":
            return
        session = text(params.get("sessionId"))
        if self.session_id is not None and session and session != self.session_id:
            return
        update = obj(params.get("update"))
        kind = text(update.get("sessionUpdate"))
        if kind == "available_commands_update":
            await self._commands(update)
            return
        if self.replaying:
            return
        handler = self._HANDLERS.get(kind)
        if handler is not None:
            await handler(self, update)

    async def asked(self, fields: JsonObject) -> ToolCall:
        """A permission request for a call: what it says joins what is known, and the call,
        once its input is known, is drawn, so the user sees what they are asked about.
        """
        call_id = text(fields.get("toolCallId"))
        call = self._calls.get(call_id) or ToolCall(call_id)
        call.update({k: v for k, v in fields.items() if k != "status"})
        if call_id:
            self._calls[call_id] = call
            await self.end_message()
            # OpenCode asks about an MCP tool before it gives its input: it is drawn when
            # it runs, with the input.
            if call.raw_input or not unknown_kind(call):
                await self._show(call)
        return call

    async def end_message(self) -> None:
        await self._end_thought()
        await self._end_text()

    async def finished(self, result: JsonObject, duration_ms: int) -> None:
        stop = text(result.get("stopReason"))
        subtype, is_error, error = _STOPS.get(stop, (stop or "unknown", False, None))
        await self._end_turn(
            ResultInfo(
                is_error=is_error,
                subtype=subtype,
                duration_ms=duration_ms,
                num_turns=1,
                errors=[error] if error else [],
                tokens=tokens(obj(result.get("usage"))),
            )
        )

    async def failed(self, message: str, duration_ms: int) -> None:
        """The engine answered the prompt with an error, such as a refused API key."""
        await self._end_turn(
            ResultInfo(
                is_error=True,
                subtype="error",
                duration_ms=duration_ms,
                num_turns=1,
                errors=[message],
            )
        )

    async def _end_turn(self, info: ResultInfo) -> None:
        await self.end_message()
        unfinished = [call for call in self._calls.values() if call.shown]
        self._calls.clear()
        if unfinished:
            await self._sink.message(
                [
                    ToolResultBlock(
                        tool_use_id=c.id, content=c.refused or UNFINISHED, is_error=True
                    )
                    for c in unfinished
                ],
                None,
            )
        await self._sink.result(info)

    async def _message_chunk(self, update: JsonObject) -> None:
        await self._end_thought()
        message_id = text(update.get("messageId"))
        if self._text and message_id != self._text_id:
            await self._end_text()
        chunk = _chunk(update)
        if chunk:
            self._text.append(chunk)
            self._text_id = message_id
            await self._sink.text_delta(chunk)

    async def _thought_chunk(self, update: JsonObject) -> None:
        await self._end_text()
        message_id = text(update.get("messageId"))
        if self._thought and message_id != self._thought_id:
            await self._end_thought()
        chunk = _chunk(update)
        if not chunk:
            return
        if not self._thought:
            self._thought_started = time.monotonic()
            await self._sink.thinking(True)
        self._thought.append(chunk)
        self._thought_id = message_id
        await self._sink.thinking_delta(chunk, None)

    async def _tool_call(self, update: JsonObject) -> None:
        await self.end_message()
        call_id = text(update.get("toolCallId"))
        if not call_id:
            return
        call = self._calls.setdefault(call_id, ToolCall(call_id))
        call.update(update)
        if call.status in _RUNNING:
            await self._show(call)
        if call.status in _ENDED:
            del self._calls[call_id]
            await self._sink.message([_result(call)], None)

    async def _usage(self, update: JsonObject) -> None:
        used, size = update.get("used"), update.get("size")
        if not isinstance(used, int) or not isinstance(size, int) or size <= 0:
            return
        # A cancelled turn reports nothing used; the last real count stays.
        if used == 0 and self._context is not None:
            return
        self._context = ContextUsage(percent=min(100.0, 100 * used / size), used=used, limit=size)

    async def _plan(self, update: JsonObject) -> None:
        steps = [
            PlanStep(text=content, status=_PLAN_STATUSES.get(text(entry.get("status")), "pending"))
            for entry in (obj(e) for e in items(update.get("entries")))
            if (content := text(entry.get("content")))
        ]
        await self._sink.plan(steps, None)

    async def _commands(self, update: JsonObject) -> None:
        commands = [
            SlashCommand(
                name=name,
                description=text(entry.get("description")) or None,
                argument_hint=text(obj(entry.get("input")).get("hint")) or None,
            )
            for entry in (obj(e) for e in items(update.get("availableCommands")))
            if (name := text(entry.get("name")))
        ]
        await self._sink.commands(CommandCatalog(commands=sorted(commands, key=lambda c: c.name)))

    async def _show(self, call: ToolCall) -> None:
        if call.shown:
            return
        call.shown = True
        name, tool_input = tool_use(call, self.nest)
        await self._sink.message([ToolUseBlock(id=call.id, name=name, input=tool_input)], None)

    async def _end_text(self) -> None:
        body = "".join(self._text)
        self._text = []
        if body:
            await self._sink.message([TextBlock(text=body)], None)

    async def _end_thought(self) -> None:
        if not self._thought:
            return
        body = "".join(self._thought)
        self._thought = []
        duration = int((time.monotonic() - self._thought_started) * 1000)
        await self._sink.message([ThinkingBlock(text=body, duration_ms=duration)], None)
        await self._sink.thinking(False)

    _HANDLERS: ClassVar[dict[str, Callable[["AcpStream", JsonObject], Awaitable[None]]]] = {
        "agent_message_chunk": _message_chunk,
        "agent_thought_chunk": _thought_chunk,
        "tool_call": _tool_call,
        "tool_call_update": _tool_call,
        "usage_update": _usage,
        "plan": _plan,
    }


def _chunk(update: JsonObject) -> str:
    content = obj(update.get("content"))
    return text(content.get("text")) if content.get("type") == "text" else ""


def _letters(key: str) -> str:
    return "".join(c for c in key.lower() if c.isalpha())
