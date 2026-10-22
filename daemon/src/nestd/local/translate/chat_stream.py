"""Reading a Chat Completions stream into plain steps both reply encoders share.

Tool calls are numbered in slots of their own: servers number calls by `index`, but some
reuse index 0 for every call and tell them apart only by id. A call starts once its name is
known; arguments that arrive before it wait. Reasoning deltas (`reasoning_content`,
`reasoning`) are dropped.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

from nestd.local.translate.values import JsonObject, integer, obj, objects, string


@dataclass(frozen=True)
class TextDelta:
    text: str


@dataclass(frozen=True)
class ToolStart:
    slot: int
    call_id: str
    name: str


@dataclass(frozen=True)
class ToolArguments:
    slot: int
    delta: str


type Step = TextDelta | ToolStart | ToolArguments


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    reasoning_tokens: int = 0


@dataclass
class _Call:
    slot: int
    upstream_id: str
    call_id: str
    name: str = ""
    started: bool = False
    waiting: list[str] = field(default_factory=list[str])


class ChunkDecoder:
    def __init__(self, new_id: Callable[[str], str]) -> None:
        self._new_id = new_id
        self._calls: dict[int, _Call] = {}
        self._slots = 0
        self.finish_reason: str | None = None
        self.usage = Usage()
        self.error: str | None = None

    def feed(self, chunk: JsonObject) -> list[Step]:
        if "error" in chunk:
            error = chunk["error"]
            self.error = string(obj(error).get("message")) or string(error) or "server error"
            return []
        if "usage" in chunk and chunk["usage"] is not None:
            self._read_usage(obj(chunk["usage"]))
        choices = objects(chunk.get("choices"))
        if not choices:
            return []
        choice = choices[0]
        finish = choice.get("finish_reason")
        if isinstance(finish, str):
            self.finish_reason = finish
        delta = obj(choice.get("delta"))
        steps: list[Step] = []
        text = string(delta.get("content"))
        if text:
            steps.append(TextDelta(text))
        for position, entry in enumerate(objects(delta.get("tool_calls"))):
            steps.extend(self._read_call(position, entry))
        return steps

    def _read_usage(self, usage: JsonObject) -> None:
        self.usage = Usage(
            input_tokens=integer(usage.get("prompt_tokens")),
            output_tokens=integer(usage.get("completion_tokens")),
            cached_tokens=integer(obj(usage.get("prompt_tokens_details")).get("cached_tokens")),
            reasoning_tokens=integer(
                obj(usage.get("completion_tokens_details")).get("reasoning_tokens")
            ),
        )

    def _read_call(self, position: int, entry: JsonObject) -> list[Step]:
        index = entry.get("index")
        key = integer(index) if isinstance(index, int) else position
        upstream_id = string(entry.get("id"))
        current = self._calls.get(key)
        if current is None or (upstream_id and upstream_id != current.upstream_id):
            current = _Call(self._slots, upstream_id, upstream_id or self._new_id("call"))
            self._slots += 1
            self._calls[key] = current
        function = obj(entry.get("function"))
        current.name = current.name or string(function.get("name"))
        arguments = string(function.get("arguments"))
        steps: list[Step] = []
        if not current.started:
            if arguments:
                current.waiting.append(arguments)
            if not current.name:
                return []
            current.started = True
            steps.append(ToolStart(current.slot, current.call_id, current.name))
            steps.extend(ToolArguments(current.slot, part) for part in current.waiting)
            current.waiting.clear()
        elif arguments:
            steps.append(ToolArguments(current.slot, arguments))
        return steps


def completion_chunk(completion: JsonObject) -> JsonObject:
    """A whole (non-streamed) completion as one stream chunk, so one decoder reads both."""
    if "error" in completion:
        return {"error": completion["error"]}
    choices = objects(completion.get("choices"))
    choice = choices[0] if choices else {}
    return {
        "choices": [
            {"delta": obj(choice.get("message")), "finish_reason": choice.get("finish_reason")}
        ],
        "usage": completion.get("usage"),
    }
