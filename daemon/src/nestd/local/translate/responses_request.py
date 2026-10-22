"""An OpenAI Responses request (what Codex sends) as a Chat Completions request.

Stateless: the whole conversation comes in `input`, so `store`, `previous_response_id`,
`reasoning`, `include` and the cache keys are left out, as are reasoning items and tools
other than functions. Custom (freeform) tools such as apply_patch are offered as functions
taking one string, `input`; the reply maps their calls back (see `ChatRequest.custom_tools`).
Chat templates often accept a system message only at the start, so leading developer and
system messages join it and later ones become user turns.
"""

import json
from dataclasses import dataclass, field

from pydantic import JsonValue

from nestd.local.translate.chat_messages import (
    assistant_message,
    function_tool,
    image_part,
    join,
    stream_options,
    text_part,
    tool_call,
    tool_choice,
    tool_message,
    user_message,
)
from nestd.local.translate.values import JsonObject, items, obj, objects, string

CUSTOM_INPUT = "input"
_CUSTOM_PARAMETERS: JsonObject = {
    "type": "object",
    "properties": {CUSTOM_INPUT: {"type": "string", "description": "The raw input."}},
    "required": [CUSTOM_INPUT],
}
_NO_PARAMETERS: JsonObject = {"type": "object", "properties": {}}
_COPIED = ("temperature", "top_p", "parallel_tool_calls")
_CHOICES = ("auto", "none", "required")
_SYSTEM_ROLES = ("system", "developer")
_TEXT_PARTS = ("input_text", "output_text")


@dataclass(frozen=True)
class ChatRequest:
    body: JsonObject
    custom_tools: frozenset[str]


def chat_request(body: JsonObject) -> ChatRequest:
    conversation = _Conversation([string(body.get("instructions"))])
    source = body.get("input")
    if isinstance(source, str):
        conversation.add_message("user", source)
    for item in objects(source):
        conversation.add(item)
    chat: JsonObject = {"model": body.get("model"), "messages": conversation.finish()}
    if "max_output_tokens" in body:
        chat["max_tokens"] = body["max_output_tokens"]
    chat.update({name: body[name] for name in _COPIED if name in body})
    tools, custom = _tools(objects(body.get("tools")))
    if tools:
        chat["tools"] = tools
    choice = _choice(body.get("tool_choice"))
    if choice is not None:
        chat["tool_choice"] = choice
    stream_options(chat, body.get("stream") is True)
    return ChatRequest(chat, custom)


@dataclass
class _Conversation:
    system: list[str]
    messages: list[JsonObject] = field(default_factory=list[JsonObject])
    # A tool's images, waiting to follow its tool messages as one user turn.
    images: list[str] = field(default_factory=list[str])

    def add(self, item: JsonObject) -> None:
        match item.get("type", "message"):
            case "message":
                self.add_message(string(item.get("role")), item.get("content"))
            case "function_call":
                self.add_call(item, string(item.get("arguments")) or "{}")
            case "custom_tool_call":
                self.add_call(item, json.dumps({CUSTOM_INPUT: string(item.get(CUSTOM_INPUT))}))
            case "function_call_output" | "custom_tool_call_output":
                self.add_output(item)
            case _:
                pass

    def add_message(self, role: str, content: JsonValue) -> None:
        parts = _parts(content)
        if role in _SYSTEM_ROLES and not self.messages:
            self.system.extend(string(part.get("text")) for part in parts)
            return
        self._flush()
        if role == "assistant":
            text = join([string(part.get("text")) for part in parts])
            message = assistant_message(text, []) if text else None
        else:
            message = user_message(parts)
        if message is not None:
            self.messages.append(message)

    def add_call(self, item: JsonObject, arguments: str) -> None:
        self._flush()
        call = tool_call(string(item.get("call_id")), string(item.get("name")), arguments)
        last = self.messages[-1] if self.messages else {}
        if last.get("role") == "assistant":
            last["tool_calls"] = [*items(last.get("tool_calls")), call]
        else:
            self.messages.append(assistant_message("", [call]))

    def add_output(self, item: JsonObject) -> None:
        output = item.get("output")
        parts = _parts(output)
        text = (
            output
            if isinstance(output, str)
            else join([string(part.get("text")) for part in parts if part["type"] == "text"])
        )
        images = [
            string(obj(part.get("image_url")).get("url"))
            for part in parts
            if part["type"] == "image_url"
        ]
        self.messages.append(tool_message(string(item.get("call_id")), text, images))
        self.images.extend(images)

    def finish(self) -> list[JsonValue]:
        self._flush()
        system = join(self.system)
        head: list[JsonValue] = [{"role": "system", "content": system}] if system else []
        return [*head, *self.messages]

    def _flush(self) -> None:
        message = user_message([image_part(url) for url in self.images])
        if message is not None:
            self.messages.append(message)
        self.images.clear()


def _parts(content: JsonValue) -> list[JsonObject]:
    """Chat content parts for Responses content: text and images, nothing else."""
    if isinstance(content, str):
        return [text_part(content)] if content else []
    parts: list[JsonObject] = []
    for part in objects(content):
        kind = part.get("type")
        if kind in _TEXT_PARTS:
            parts.append(text_part(string(part.get("text"))))
        elif kind == "input_image" and string(part.get("image_url")):
            parts.append(image_part(string(part.get("image_url"))))
    return parts


def _tools(tools: list[JsonObject]) -> tuple[list[JsonValue], frozenset[str]]:
    offered: list[JsonValue] = []
    custom: set[str] = set()
    for tool in tools:
        name = string(tool.get("name"))
        description = string(tool.get("description"))
        match tool.get("type"):
            case "function" if name:
                offered.append(
                    function_tool(name, description, tool.get("parameters") or _NO_PARAMETERS)
                )
            case "custom" if name:
                offered.append(function_tool(name, _custom_description(tool), _CUSTOM_PARAMETERS))
                custom.add(name)
            case _:
                pass
    return offered, frozenset(custom)


def _custom_description(tool: JsonObject) -> str:
    grammar = obj(tool.get("format"))
    definition = string(grammar.get("definition"))
    rule = (
        f"The input follows this {string(grammar.get('syntax'))} grammar:\n{definition}"
        if definition
        else ""
    )
    return join([string(tool.get("description")), rule])


def _choice(value: JsonValue) -> JsonValue:
    if isinstance(value, str):
        return value if value in _CHOICES else None
    choice = obj(value)
    if choice.get("type") in ("function", "custom"):
        return tool_choice(string(choice.get("name")))
    return None
