"""Claude Code's requests to a server with its own Anthropic Messages API, and two fixes.

Claude Code sends mid-conversation messages with role "system". LM Studio hoists them to
the start of the prompt, which changes the prompt's prefix on every request, so the server's
prefix cache misses and each turn reads the whole conversation again (live: 3262 of 15119
tokens reused and 96 s, against 14908 and 3 s as user messages). They become user messages
where they are; nothing else in the request changes.

LM Studio 0.4 also counts cache reads inside `input_tokens`, where Anthropic leaves them
out. Claude Code adds the two, believes the context twice as full and compacts after almost
every step, so for such a server the replies' usage is put right (`fixed_reply`,
`UsageFix`); every other byte is passed on as it came.
"""

import json

from pydantic import JsonValue, TypeAdapter, ValidationError

from nestd.local.translate.values import JsonObject, integer, obj

_JSON = TypeAdapter[JsonValue](JsonValue)
_SEPARATORS = (b"\r\n\r\n", b"\n\n")
_DATA = b"data:"


def native_request(body: JsonObject) -> JsonObject:
    messages = body.get("messages")
    if not isinstance(messages, list):
        return body
    rewritten: list[JsonValue] = [_as_user(message) for message in messages]
    return {**body, "messages": rewritten}


def _as_user(message: JsonValue) -> JsonValue:
    if isinstance(message, dict) and message.get("role") == "system":
        return {**message, "role": "user"}
    return message


def fixed_reply(content: bytes) -> bytes:
    """A whole (non-streamed) reply with its usage put right; unchanged when it needs none."""
    body = _parse(content)
    usage = _fixed(obj(body.get("usage")))
    if usage is None:
        return content
    return json.dumps({**body, "usage": usage}).encode()


class UsageFix:
    """Puts a stream's usage right in `message_start` and `message_delta`; each event goes
    on as soon as it is whole, and any other event exactly as it came."""

    def __init__(self) -> None:
        self._buffer = b""

    def feed(self, piece: bytes) -> bytes:
        self._buffer += piece
        out = b""
        while (end := self._event_end()) is not None:
            event, self._buffer = self._buffer[:end], self._buffer[end:]
            out += _fixed_event(event)
        return out

    def finish(self) -> bytes:
        rest, self._buffer = self._buffer, b""
        return rest

    def _event_end(self) -> int | None:
        ends = [
            found + len(separator)
            for separator in _SEPARATORS
            if (found := self._buffer.find(separator)) >= 0
        ]
        return min(ends) if ends else None


def _fixed(usage: JsonObject) -> JsonObject | None:
    cached = integer(usage.get("cache_read_input_tokens"))
    if cached <= 0 or "input_tokens" not in usage:
        return None
    return {**usage, "input_tokens": max(integer(usage["input_tokens"]) - cached, 0)}


def _parse(content: bytes) -> JsonObject:
    try:
        return obj(_JSON.validate_json(content))
    except ValidationError:
        return {}


def _fixed_event(event: bytes) -> bytes:
    newline = b"\r\n" if event.endswith(b"\r\n\r\n") else b"\n"
    lines = event[: -2 * len(newline)].split(newline)
    payload = b"\n".join(
        line.removeprefix(_DATA).removeprefix(b" ") for line in lines if line.startswith(_DATA)
    )
    data = _parse(payload)
    fixed = _fixed_data(data)
    if fixed is None:
        return event
    kept = [line for line in lines if not line.startswith(_DATA)]
    return newline.join([*kept, b"data: " + json.dumps(fixed).encode()]) + newline * 2


def _fixed_data(data: JsonObject) -> JsonObject | None:
    match data.get("type"):
        case "message_start":
            message = obj(data.get("message"))
            usage = _fixed(obj(message.get("usage")))
            return None if usage is None else {**data, "message": {**message, "usage": usage}}
        case "message_delta":
            usage = _fixed(obj(data.get("usage")))
            return None if usage is None else {**data, "usage": usage}
        case _:
            return None
