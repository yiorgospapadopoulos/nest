"""What of a stored event goes into the search index, as (kind, text) entries.

User messages, the main agent's text, its tool calls (name and short argument) and the
start of tool results. Thinking and subagent messages are left out: the transcript does
not show them, so a hit there could not be opened.
"""

from dataclasses import dataclass

from pydantic import JsonValue

from harness.events import types
from harness.tracking.steps import short_arg

# Assistant text is kept whole up to this length; tool results only their start.
MAX_TEXT = 20_000
MAX_RESULT = 500


@dataclass(frozen=True)
class Entry:
    # user, assistant, tool or tool_result.
    kind: str
    text: str


def entries(event_type: str, payload: dict[str, JsonValue]) -> list[Entry]:
    if event_type == types.SESSION_USER_MESSAGE:
        text = payload.get("text")
        return [Entry("user", text[:MAX_TEXT])] if isinstance(text, str) and text.strip() else []
    if event_type != types.SESSION_MESSAGE or payload.get("parent_tool_use_id") is not None:
        return []
    blocks = payload.get("blocks")
    texts: list[str] = []
    tools: list[str] = []
    results: list[str] = []
    for block in blocks if isinstance(blocks, list) else []:
        if not isinstance(block, dict):
            continue
        kind = block.get("type")
        if kind == "text":
            _add(texts, block.get("text"))
        elif kind == "tool_use":
            tools.append(_tool_call(block))
        elif kind == "tool_result":
            content = block.get("content")
            _add(results, " ".join(content.split()) if isinstance(content, str) else None)
    found = [
        Entry("assistant", "\n".join(texts)[:MAX_TEXT]),
        Entry("tool", "\n".join(tools)),
        Entry("tool_result", " ".join(results)[:MAX_RESULT]),
    ]
    return [entry for entry in found if entry.text]


def _add(parts: list[str], text: JsonValue | None) -> None:
    if isinstance(text, str) and text.strip():
        parts.append(text)


def _tool_call(block: dict[str, JsonValue]) -> str:
    name = block.get("name")
    tool_input = block.get("input")
    arg = short_arg(tool_input, None) if isinstance(tool_input, dict) else ""
    return " ".join(part for part in (str(name or "Tool"), arg) if part)
