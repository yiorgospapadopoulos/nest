"""Read one Claude Code transcript (`<session id>.jsonl`) into harness's message shapes.

The file format is Claude Code's own and undocumented, so every line and field is read
defensively: lines that are not JSON objects, and fields of an unexpected type, are skipped.
"""

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from pydantic import JsonValue

from harness.events import types
from harness.providers import base
from harness.sessions.titles import short_title

type Raw = dict[str, object]

# User text that Claude Code adds itself: command output, hook context, notifications.
_INTERNAL = re.compile(
    r"^\s*(?:<(?:local-command-stdout|local-command-stderr|local-command-caveat"
    r"|command-message|command-args|task-notification|bash-input|bash-stdout|bash-stderr"
    r"|system-reminder|session-start-hook|user-prompt-submit-hook|tick|goal"
    r"|ide_opened_file|ide_selection)\b|\[Request interrupted by user)"
)
_COMMAND = re.compile(r"<command-name>\s*(.*?)\s*</command-name>", re.DOTALL)
_COMMAND_ARGS = re.compile(r"<command-args>\s*(.*?)\s*</command-args>", re.DOTALL)
_IMAGE = "[image]"


@dataclass(frozen=True)
class HistoryItem:
    """One message as a harness session event: its type, payload and time."""

    type: str
    payload: dict[str, JsonValue]
    ts: datetime | None


@dataclass(frozen=True)
class Transcript:
    title: str | None
    first_prompt: str | None
    cwd: Path | None
    created_at: datetime | None
    # What started the chat: `cli`, `claude-desktop`, or `sdk-py` and the like for a program.
    entrypoint: str | None
    history: list[HistoryItem]

    @property
    def message_count(self) -> int:
        """User prompts and assistant replies with text; tool calls are not counted."""
        return sum(1 for item in self.history if _counts(item))

    @property
    def display_title(self) -> str | None:
        """Claude Code's title, else the first prompt shortened; None for an empty chat."""
        if self.title:
            return self.title
        return short_title(self.first_prompt) if self.first_prompt else None


def read_transcript(path: Path) -> Transcript:
    """Raises OSError when the file cannot be read."""
    return parse_transcript(path.read_text(encoding="utf-8", errors="replace"))


def parse_transcript(text: str) -> Transcript:
    entries = list(_entries(text))
    history = [item for entry in _main_chain(entries) for item in _items(entry)]
    first_prompt = next(
        (_text_of(item) for item in history if item.type == types.SESSION_USER_MESSAGE), None
    )
    return Transcript(
        title=_title(entries),
        first_prompt=first_prompt,
        cwd=next((Path(cwd) for entry in entries if (cwd := _str(entry, "cwd"))), None),
        created_at=next((ts for entry in entries if (ts := _time(entry)) is not None), None),
        entrypoint=next((value for entry in entries if (value := _str(entry, "entrypoint"))), None),
        history=history,
    )


def _entries(text: str) -> Iterator[Raw]:
    for line in text.splitlines():
        try:
            value: object = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict):
            yield cast("Raw", value)


def _title(entries: list[Raw]) -> str | None:
    """A title set in Claude Code, else its generated one, else an older summary line."""
    for key, entry_type in (("customTitle", None), ("aiTitle", None), ("summary", "summary")):
        titles = [
            title.strip()
            for entry in entries
            if (entry_type is None or entry.get("type") == entry_type)
            and (title := _str(entry, key))
            and title.strip()
        ]
        if titles:
            return titles[-1]
    return None


def _main_chain(entries: list[Raw]) -> list[Raw]:
    """The conversation as it stands: from the newest message back along its parents.

    Rewound or edited branches are left out. A compaction boundary has no parent but a
    logical one, which is followed so the history before the compaction stays readable.
    """
    nodes = {uuid: entry for entry in entries if (uuid := _str(entry, "uuid"))}
    leaf = next(
        (
            uuid
            for entry in reversed(entries)
            if entry.get("type") in ("user", "assistant")
            and entry.get("isSidechain") is not True
            and (uuid := _str(entry, "uuid"))
        ),
        None,
    )
    chain: list[Raw] = []
    seen: set[str] = set()
    current = leaf
    while current is not None and current not in seen:
        seen.add(current)
        entry = nodes.get(current)
        if entry is None:
            break
        chain.append(entry)
        current = _str(entry, "parentUuid") or _str(entry, "logicalParentUuid")
    chain.reverse()
    return chain


def _items(entry: Raw) -> list[HistoryItem]:
    if any(entry.get(flag) is True for flag in ("isSidechain", "isMeta", "isCompactSummary")):
        return []
    message = entry.get("message")
    content = cast("Raw", message).get("content") if isinstance(message, dict) else None
    ts = _time(entry)
    if entry.get("type") == "assistant":
        blocks = [block for raw in _list(content) if (block := _block(raw)) is not None]
        return [_message(blocks, ts)] if blocks else []
    if entry.get("type") != "user":
        return []
    if isinstance(content, str):
        text = _prompt(content)
        return [_user(text, ts)] if text else []
    raws = _list(content)
    results = [
        block
        for raw in raws
        if raw.get("type") == "tool_result" and (block := _block(raw)) is not None
    ]
    texts = [
        text
        for raw in raws
        if raw.get("type") == "text" and (text := _prompt(_str(raw, "text") or ""))
    ]
    texts += [_IMAGE for raw in raws if raw.get("type") == "image"]
    items = [_message(results, ts)] if results else []
    if texts:
        items.append(_user("\n".join(texts), ts))
    return items


def _prompt(text: str) -> str | None:
    """What the user typed: slash commands as `/name args`, Claude Code's own text dropped."""
    command = _COMMAND.search(text)
    if command is not None:
        args = _COMMAND_ARGS.search(text)
        return f"{command.group(1)} {args.group(1) if args else ''}".strip() or None
    if _INTERNAL.match(text):
        return None
    return text.strip() or None


def _block(raw: Raw) -> base.MessageBlock | None:
    match raw.get("type"):
        case "text":
            text = _str(raw, "text")
            return base.TextBlock(text=text) if text is not None else None
        case "thinking" | "redacted_thinking":
            return base.ThinkingBlock(text=_str(raw, "thinking") or "")
        case "tool_use" | "server_tool_use":
            block_id, name, tool_input = _str(raw, "id"), _str(raw, "name"), raw.get("input")
            if block_id is None or name is None or not isinstance(tool_input, dict):
                return None
            return base.ToolUseBlock(
                id=block_id, name=name, input=cast("dict[str, JsonValue]", tool_input)
            )
        case _:
            tool_use_id = _str(raw, "tool_use_id")
            if tool_use_id is None:
                return None
            # tool_result, or a server tool's result such as web_search_tool_result.
            return base.ToolResultBlock(
                tool_use_id=tool_use_id,
                content=_result_text(raw.get("content")),
                is_error=raw.get("is_error") is True,
            )


def _result_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if content is None:
        return ""
    if not isinstance(content, list):
        return json.dumps(content)
    parts = [
        _str(item, "text") or "" if item.get("type") == "text" else f"[{item.get('type')}]"
        for item in _list(cast("object", content))
    ]
    return "\n".join(parts)


def _message(blocks: list[base.MessageBlock], ts: datetime | None) -> HistoryItem:
    return HistoryItem(
        types.SESSION_MESSAGE,
        {"blocks": [block.model_dump(mode="json") for block in blocks], "parent_tool_use_id": None},
        ts,
    )


def _user(text: str, ts: datetime | None) -> HistoryItem:
    return HistoryItem(types.SESSION_USER_MESSAGE, {"text": text, "attachments": []}, ts)


def _counts(item: HistoryItem) -> bool:
    if item.type == types.SESSION_USER_MESSAGE:
        return True
    blocks = cast("list[Raw]", item.payload["blocks"])
    return any(block["type"] == "text" for block in blocks)


def _text_of(item: HistoryItem) -> str:
    return cast("str", item.payload["text"])


def _list(value: object) -> list[Raw]:
    """The dict items of a JSON list; anything else is empty."""
    items = cast("list[object]", value) if isinstance(value, list) else []
    return [cast("Raw", item) for item in items if isinstance(item, dict)]


def _str(raw: Raw, key: str) -> str | None:
    value = raw.get(key)
    return value if isinstance(value, str) else None


def _time(entry: Raw) -> datetime | None:
    value = _str(entry, "timestamp")
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
