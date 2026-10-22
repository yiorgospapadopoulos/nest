"""A Chat Completions reply as OpenAI Responses stream events, and as the whole response.

Text is one message item; each tool call is a function_call item, or a custom_tool_call
item for a custom tool, whose `input` is unwrapped from the one-argument function it was
offered as. As with the Anthropic reply, tool items stay open until the reply ends.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from pydantic import JsonValue, TypeAdapter, ValidationError

from nestd.local.translate.chat_stream import ChunkDecoder, TextDelta, ToolStart
from nestd.local.translate.responses_request import CUSTOM_INPUT
from nestd.local.translate.sse import encode
from nestd.local.translate.values import JsonObject, new_id, obj

_JSON = TypeAdapter[JsonValue](JsonValue)
type _Kind = Literal["message", "function_call", "custom_tool_call"]


@dataclass
class _Item:
    kind: _Kind
    item_id: str
    output_index: int
    call_id: str = ""
    name: str = ""
    content: str = ""
    open: bool = True

    def json(self) -> JsonObject:
        status = "in_progress" if self.open else "completed"
        match self.kind:
            case "message":
                content: list[JsonValue] = [] if self.open else [_text_part(self.content)]
                return {
                    "type": "message",
                    "id": self.item_id,
                    "role": "assistant",
                    "status": status,
                    "content": content,
                }
            case "function_call":
                arguments = "" if self.open else self.content
                return {**self._call(status), "arguments": arguments}
            case _:
                custom = "" if self.open else _custom_input(self.content)
                return {**self._call(status), CUSTOM_INPUT: custom}

    def _call(self, status: str) -> JsonObject:
        return {
            "type": self.kind,
            "id": self.item_id,
            "call_id": self.call_id,
            "name": self.name,
            "status": status,
        }


class ResponsesReply:
    def __init__(
        self,
        model: str,
        custom_tools: frozenset[str],
        created_at: int,
        ids: Callable[[str], str] = new_id,
    ) -> None:
        self._decoder = ChunkDecoder(ids)
        self._ids = ids
        self._id = ids("resp")
        self._model = model
        self._custom = custom_tools
        self._created_at = created_at
        self._items: list[_Item] = []
        self._text: _Item | None = None
        self._tools: dict[int, _Item] = {}
        self._sequence = 0
        self.done = False
        self.error: str | None = None

    def start(self) -> bytes:
        return self._event("response.created", {"response": self._response("in_progress")})

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
                custom = step.name in self._custom
                kind: _Kind = "custom_tool_call" if custom else "function_call"
                item = self._new_item(kind, "ctc" if custom else "fc")
                item.call_id = step.call_id
                item.name = step.name
                self._tools[step.slot] = item
                out += self._added(item)
            else:
                item = self._tools[step.slot]
                item.content += step.delta
                if item.kind == "function_call":
                    out += self._event(
                        "response.function_call_arguments.delta",
                        {**_where(item), "delta": step.delta},
                    )
        return out

    def finish(self) -> bytes:
        out = b"".join(self._close(item) for item in self._items)
        self.done = True
        if self._decoder.finish_reason == "length":
            return out + self._event("response.incomplete", {"response": self.response()})
        return out + self._event("response.completed", {"response": self.response()})

    def fail(self, message: str) -> bytes:
        self.done = True
        self.error = message
        return self._event("response.failed", {"response": self.response()})

    def response(self) -> JsonObject:
        if self.error is not None:
            failed = self._response("failed")
            failed["error"] = {"code": "server_error", "message": self.error}
            return failed
        if self._decoder.finish_reason == "length":
            incomplete = self._response("incomplete")
            incomplete["incomplete_details"] = {"reason": "max_output_tokens"}
            return incomplete
        return self._response("completed")

    def _response(self, status: str) -> JsonObject:
        usage = self._decoder.usage
        output: list[JsonValue] = [item.json() for item in self._items]
        return {
            "id": self._id,
            "object": "response",
            "created_at": self._created_at,
            "status": status,
            "model": self._model,
            "output": output,
            "usage": None
            if status == "in_progress"
            else {
                "input_tokens": usage.input_tokens,
                "input_tokens_details": {"cached_tokens": usage.cached_tokens},
                "output_tokens": usage.output_tokens,
                "output_tokens_details": {"reasoning_tokens": usage.reasoning_tokens},
                "total_tokens": usage.input_tokens + usage.output_tokens,
            },
        }

    def _new_item(self, kind: _Kind, prefix: str) -> _Item:
        item = _Item(kind, self._ids(prefix), len(self._items))
        self._items.append(item)
        return item

    def _added(self, item: _Item) -> bytes:
        return self._event(
            "response.output_item.added", {"output_index": item.output_index, "item": item.json()}
        )

    def _add_text(self, text: str) -> bytes:
        out = b""
        if self._text is None:
            self._text = self._new_item("message", "msg")
            out = self._added(self._text) + self._event(
                "response.content_part.added",
                {**_where(self._text), "content_index": 0, "part": _text_part("")},
            )
        self._text.content += text
        return out + self._event(
            "response.output_text.delta",
            {**_where(self._text), "content_index": 0, "delta": text},
        )

    def _close_text(self) -> bytes:
        if self._text is None:
            return b""
        out = self._close(self._text)
        self._text = None
        return out

    def _close(self, item: _Item) -> bytes:
        if not item.open:
            return b""
        item.open = False
        out = b""
        if item.kind == "message":
            where: JsonObject = {**_where(item), "content_index": 0}
            out = self._event("response.output_text.done", {**where, "text": item.content})
            out += self._event(
                "response.content_part.done", {**where, "part": _text_part(item.content)}
            )
        elif item.kind == "function_call":
            out = self._event(
                "response.function_call_arguments.done", {**_where(item), "arguments": item.content}
            )
        return out + self._event(
            "response.output_item.done", {"output_index": item.output_index, "item": item.json()}
        )

    def _event(self, kind: str, fields: JsonObject) -> bytes:
        data: JsonObject = {"type": kind, "sequence_number": self._sequence, **fields}
        self._sequence += 1
        return encode(kind, data)


def _where(item: _Item) -> JsonObject:
    return {"item_id": item.item_id, "output_index": item.output_index}


def _text_part(text: str) -> JsonObject:
    return {"type": "output_text", "text": text, "annotations": []}


def _custom_input(arguments: str) -> str:
    """The `input` argument, or the raw arguments when the model wrote the input itself."""
    try:
        value = obj(_JSON.validate_json(arguments))
    except ValidationError:
        return arguments
    found = value.get(CUSTOM_INPUT)
    return found if isinstance(found, str) else arguments
