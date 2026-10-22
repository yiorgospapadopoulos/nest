"""A Chat Completions reply as Anthropic Messages stream events, and as the whole message.

One content block per tool call. A text block closes when a tool call starts; tool blocks
stay open until the reply ends, because Claude Code collects each block by its index, so
a server that interleaves several calls' arguments still lands each in its own block.
"""

from collections.abc import Callable
from dataclasses import dataclass

from pydantic import JsonValue, TypeAdapter, ValidationError

from nestd.local.translate.chat_stream import ChunkDecoder, TextDelta, ToolStart
from nestd.local.translate.sse import encode
from nestd.local.translate.values import JsonObject, new_id

_JSON = TypeAdapter[JsonValue](JsonValue)


@dataclass
class _Block:
    tool: bool
    content: str = ""
    call_id: str = ""
    name: str = ""
    open: bool = True


class AnthropicReply:
    def __init__(self, model: str, ids: Callable[[str], str] = new_id) -> None:
        self._decoder = ChunkDecoder(ids)
        self._id = ids("msg")
        self._model = model
        self._blocks: list[_Block] = []
        self._text: int | None = None
        self._tools: dict[int, int] = {}
        self.done = False
        self.error: str | None = None

    def start(self) -> bytes:
        message: JsonObject = {
            "id": self._id,
            "type": "message",
            "role": "assistant",
            "model": self._model,
            "content": [],
            "stop_reason": None,
            "stop_sequence": None,
            "usage": {"input_tokens": 0, "output_tokens": 0},
        }
        return _event("message_start", {"message": message})

    def feed(self, chunk: JsonObject) -> bytes:
        steps = self._decoder.feed(chunk)
        if self._decoder.error is not None:
            return self.fail(self._decoder.error)
        out = b""
        for step in steps:
            if isinstance(step, TextDelta):
                out += self._add_text(step.text)
            elif isinstance(step, ToolStart):
                out += self._close_text()
                self._tools[step.slot] = len(self._blocks)
                out += self._open(_Block(tool=True, call_id=step.call_id, name=step.name))
            else:
                index = self._tools[step.slot]
                self._blocks[index].content += step.delta
                delta: JsonObject = {"type": "input_json_delta", "partial_json": step.delta}
                out += _event("content_block_delta", {"index": index, "delta": delta})
        return out

    def finish(self) -> bytes:
        out = b"".join(self._close(index) for index in range(len(self._blocks)))
        self.done = True
        usage = self._usage()
        delta: JsonObject = {"stop_reason": self._stop_reason(), "stop_sequence": None}
        out += _event("message_delta", {"delta": delta, "usage": usage})
        return out + _event("message_stop", {})

    def fail(self, message: str) -> bytes:
        self.done = True
        self.error = message
        return _event("error", {"error": {"type": "api_error", "message": message}})

    def message(self) -> JsonObject:
        content: list[JsonValue] = [
            {"type": "tool_use", "id": block.call_id, "name": block.name, "input": _input(block)}
            if block.tool
            else {"type": "text", "text": block.content}
            for block in self._blocks
        ]
        return {
            "id": self._id,
            "type": "message",
            "role": "assistant",
            "model": self._model,
            "content": content,
            "stop_reason": self._stop_reason(),
            "stop_sequence": None,
            "usage": self._usage(),
        }

    def _add_text(self, text: str) -> bytes:
        out = b""
        if self._text is None:
            self._text = len(self._blocks)
            out = self._open(_Block(tool=False))
        self._blocks[self._text].content += text
        delta: JsonObject = {"type": "text_delta", "text": text}
        return out + _event("content_block_delta", {"index": self._text, "delta": delta})

    def _open(self, block: _Block) -> bytes:
        index = len(self._blocks)
        self._blocks.append(block)
        start: JsonObject = (
            {"type": "tool_use", "id": block.call_id, "name": block.name, "input": {}}
            if block.tool
            else {"type": "text", "text": ""}
        )
        return _event("content_block_start", {"index": index, "content_block": start})

    def _close_text(self) -> bytes:
        if self._text is None:
            return b""
        out = self._close(self._text)
        self._text = None
        return out

    def _close(self, index: int) -> bytes:
        block = self._blocks[index]
        if not block.open:
            return b""
        block.open = False
        return _event("content_block_stop", {"index": index})

    def _stop_reason(self) -> str:
        if self._decoder.finish_reason == "length":
            return "max_tokens"
        return "tool_use" if self._tools else "end_turn"

    def _usage(self) -> JsonObject:
        usage = self._decoder.usage
        return {"input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens}


def _event(kind: str, fields: JsonObject) -> bytes:
    return encode(kind, {"type": kind, **fields})


def _input(block: _Block) -> JsonObject:
    """The parsed arguments; anything but a JSON object reads as no input, which the agent
    reports back to the model as a bad tool call."""
    try:
        value = _JSON.validate_json(block.content or "{}")
    except ValidationError:
        return {}
    return value if isinstance(value, dict) else {}
