"""The kept part of a rewound or forked chat, for an engine that cannot cut its own
conversation (an ACP engine, D174): its new session gets it with its first message.

Only what was said is kept: the user's messages, and the agent's text with one line per
tool it used. The oldest is dropped first when it is too long.
"""

from collections.abc import Sequence

from pydantic import JsonValue

from nestd.events import types
from nestd.events.models import Event

# About 20k tokens: enough to go on from, far below any engine's window.
MAX_CHARS = 80_000
_LEAD = (
    "This conversation continues an earlier one, which was cut short at this point. What "
    "was said so far, oldest first:"
)
_END = "End of the earlier conversation. The user's new message follows."


def kept_history(events: Sequence[Event]) -> str | None:
    """The conversation in `events`, as a block for the engine; None when it is empty."""
    entries = [entry for event in events if (entry := _entry(event))]
    kept: list[str] = []
    size = 0
    for entry in reversed(entries):
        size += len(entry) + 2
        if size > MAX_CHARS and kept:
            break
        kept.append(entry[-MAX_CHARS:])
    if not kept:
        return None
    return "\n\n".join([_LEAD, *reversed(kept), _END])


def _entry(event: Event) -> str | None:
    if event.type == types.SESSION_USER_MESSAGE:
        said = event.payload.get("text")
        return f"User: {said}" if isinstance(said, str) and said.strip() else None
    if event.type != types.SESSION_MESSAGE or event.payload.get("parent_tool_use_id"):
        return None
    lines = [line for block in _blocks(event.payload.get("blocks")) if (line := _line(block))]
    return "Agent: " + "\n".join(lines) if lines else None


def _blocks(value: JsonValue) -> list[dict[str, JsonValue]]:
    if not isinstance(value, list):
        return []
    return [block for block in value if isinstance(block, dict)]


def _line(block: dict[str, JsonValue]) -> str | None:
    kind = block.get("type")
    if kind == "text":
        said = block.get("text")
        return said if isinstance(said, str) and said.strip() else None
    if kind == "tool_use":
        return f"(used the tool {block.get('name')})"
    return None
