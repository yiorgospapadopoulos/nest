"""A Codex thread's recorded turns as Nest session events, drawn like a Nest Codex chat's.

Each finished item becomes what a live run makes of it (`providers/codex_events`): the
agent's text, its reasoning as a thinking block, and tool items as calls with Claude Code's
tool names followed by their results. Sub-agent calls, plans and compactions are left out.
"""

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import cast

from pydantic import JsonValue

from nestd.claude_sessions.transcript import HistoryItem
from nestd.events import types
from nestd.providers.base import MessageBlock, TextBlock, ThinkingBlock
from nestd.providers.codex_items import TOOL_ITEMS, items, obj, text, tool_results, tool_uses
from nestd.providers.codex_rpc import JsonObject

_IMAGE = "[image]"
_IMAGES = frozenset({"image", "localImage"})


def thread_history(turns: list[JsonObject]) -> list[HistoryItem]:
    history: list[HistoryItem] = []
    for turn in turns:
        started = _time(turn.get("startedAt"))
        finished = _time(turn.get("completedAt")) or started
        for entry in items(turn.get("items")):
            item = obj(entry)
            at = started if item.get("type") == "userMessage" else finished
            history.extend(_events(item, at))
    return history


def first_prompt(history: list[HistoryItem]) -> str | None:
    return next(
        (
            cast("str", item.payload["text"])
            for item in history
            if item.type == types.SESSION_USER_MESSAGE
        ),
        None,
    )


def message_count(history: list[HistoryItem]) -> int:
    """User messages and agent messages with text, as for Claude Code chats."""
    return sum(1 for item in history if _counts(item))


def _events(item: JsonObject, at: datetime | None) -> Iterator[HistoryItem]:
    kind = item.get("type")
    if kind == "userMessage":
        body = _user_text(item)
        if body:
            yield HistoryItem(types.SESSION_USER_MESSAGE, {"text": body, "attachments": []}, at)
    elif kind == "agentMessage":
        body = text(item.get("text"))
        if body:
            yield _message([TextBlock(text=body)], at)
    elif kind == "reasoning":
        # The summary, else the raw reasoning; often neither, which shows nothing.
        body = _joined(item.get("summary")) or _joined(item.get("content"))
        if body:
            yield _message([ThinkingBlock(text=body)], at)
    elif kind == "webSearch" or kind in TOOL_ITEMS:
        uses, results = tool_uses(item), tool_results(item)
        if uses:
            yield _message(list(uses), at)
        if results:
            yield _message(list(results), at)


def _user_text(item: JsonObject) -> str:
    parts: list[str] = []
    for entry in items(item.get("content")):
        part = obj(entry)
        if part.get("type") == "text":
            parts.append(text(part.get("text")))
        elif part.get("type") in _IMAGES:
            parts.append(_IMAGE)
    return "\n".join(part for part in parts if part).strip()


def _message(blocks: list[MessageBlock], at: datetime | None) -> HistoryItem:
    return HistoryItem(
        types.SESSION_MESSAGE,
        {"blocks": [block.model_dump(mode="json") for block in blocks], "parent_tool_use_id": None},
        at,
    )


def _counts(item: HistoryItem) -> bool:
    if item.type == types.SESSION_USER_MESSAGE:
        return True
    blocks = cast("list[dict[str, JsonValue]]", item.payload["blocks"])
    return any(block["type"] == "text" for block in blocks)


def _joined(parts: JsonValue | None) -> str:
    return "\n\n".join(part for part in (text(p) for p in items(parts)) if part)


def _time(value: JsonValue | None) -> datetime | None:
    return datetime.fromtimestamp(value, UTC) if isinstance(value, int | float) else None
