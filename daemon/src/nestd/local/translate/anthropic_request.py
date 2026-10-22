"""An Anthropic Messages request (what Claude Code sends) as a Chat Completions request.

Thinking, context_management, output_config, metadata, cache_control and betas mean nothing
to a chat server and are left out, as are Anthropic's server tools (web search and the
like, which have no input schema).
"""

import json

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
from nestd.local.translate.values import JsonObject, obj, objects, string

_COPIED = ("max_tokens", "temperature", "top_p")
_CHOICES: dict[str, JsonValue] = {"auto": "auto", "any": "required", "none": "none"}


def chat_request(body: JsonObject) -> JsonObject:
    messages: list[JsonValue] = []
    system = _text(body.get("system"))
    if system:
        messages.append({"role": "system", "content": system})
    for message in objects(body.get("messages")):
        messages.extend(_messages(message))
    chat: JsonObject = {"model": body.get("model"), "messages": messages}
    chat.update({name: body[name] for name in _COPIED if name in body})
    if "stop_sequences" in body:
        chat["stop"] = body["stop_sequences"]
    tools: list[JsonValue] = [
        function_tool(
            string(tool.get("name")), string(tool.get("description")), tool["input_schema"]
        )
        for tool in objects(body.get("tools"))
        if "input_schema" in tool
    ]
    if tools:
        chat["tools"] = tools
    if "tool_choice" in body:
        _choose(chat, obj(body["tool_choice"]))
    stream_options(chat, body.get("stream") is True)
    return chat


def _text(value: JsonValue) -> str:
    if isinstance(value, str):
        return value
    return join(
        [string(block.get("text")) for block in objects(value) if block.get("type") == "text"]
    )


def _image_url(block: JsonObject) -> str:
    source = obj(block.get("source"))
    match source.get("type"):
        case "base64":
            return f"data:{string(source.get('media_type'))};base64,{string(source.get('data'))}"
        case "url":
            return string(source.get("url"))
        case _:
            return ""


def _messages(message: JsonObject) -> list[JsonObject]:
    content = message.get("content")
    blocks: list[JsonObject] = (
        [{"type": "text", "text": content}] if isinstance(content, str) else objects(content)
    )
    found = _assistant(blocks) if message.get("role") == "assistant" else _user(blocks)
    return [entry for entry in found if entry is not None]


def _assistant(blocks: list[JsonObject]) -> list[JsonObject | None]:
    texts: list[str] = []
    calls: list[JsonObject] = []
    for block in blocks:
        match block.get("type"):
            case "text":
                texts.append(string(block.get("text")))
            case "tool_use":
                arguments = json.dumps(obj(block.get("input")))
                calls.append(
                    tool_call(string(block.get("id")), string(block.get("name")), arguments)
                )
            case _:
                pass
    text = join(texts)
    return [assistant_message(text, calls)] if text or calls else []


def _user(blocks: list[JsonObject]) -> list[JsonObject | None]:
    results: list[JsonObject | None] = []
    tool_images: list[JsonObject] = []
    parts: list[JsonObject] = []
    for block in blocks:
        match block.get("type"):
            case "text":
                text = string(block.get("text"))
                if text:
                    parts.append(text_part(text))
            case "image":
                url = _image_url(block)
                if url:
                    parts.append(image_part(url))
            case "tool_result":
                images = _result_images(block)
                text = _text(block.get("content"))
                if text and block.get("is_error") is True:
                    text = f"Error: {text}"
                results.append(tool_message(string(block.get("tool_use_id")), text, images))
                tool_images.extend(image_part(url) for url in images)
            case _:
                pass
    return [*results, user_message([*tool_images, *parts])]


def _result_images(block: JsonObject) -> list[str]:
    urls = [
        _image_url(part) for part in objects(block.get("content")) if part.get("type") == "image"
    ]
    return [url for url in urls if url]


def _choose(chat: JsonObject, choice: JsonObject) -> None:
    kind = string(choice.get("type"))
    if kind == "tool":
        chat["tool_choice"] = tool_choice(string(choice.get("name")))
    elif kind in _CHOICES:
        chat["tool_choice"] = _CHOICES[kind]
    if choice.get("disable_parallel_tool_use") is True:
        chat["parallel_tool_calls"] = False
