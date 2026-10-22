"""Server-sent events: framing what goes to the agent, reading what the server sends."""

import json
from collections.abc import AsyncIterable, AsyncIterator

from pydantic import JsonValue, TypeAdapter, ValidationError

from nestd.local.translate.values import JsonObject

DONE = "[DONE]"
_JSON = TypeAdapter[JsonValue](JsonValue)


def encode(event: str | None, data: JsonObject) -> bytes:
    head = f"event: {event}\n" if event is not None else ""
    return f"{head}data: {json.dumps(data, separators=(',', ':'))}\n\n".encode()


async def chunks(lines: AsyncIterable[str]) -> AsyncIterator[JsonObject]:
    """The JSON objects of the `data:` lines, up to `[DONE]` or the end of the stream;
    anything unreadable is skipped."""
    async for line in lines:
        if not line.startswith("data:"):
            continue
        payload = line.removeprefix("data:").strip()
        if payload == DONE:
            return
        try:
            value = _JSON.validate_json(payload)
        except ValidationError:
            continue
        if isinstance(value, dict):
            yield value
