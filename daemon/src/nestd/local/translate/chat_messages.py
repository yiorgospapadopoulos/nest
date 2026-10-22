"""Building Chat Completions messages, shared by both request mappings."""

from pydantic import JsonValue

from nestd.local.translate.values import JsonObject

# Chat servers take only text in a tool message, so a tool's images follow as a user turn.
IMAGE_BELOW = "(image below)"


def join(texts: list[str]) -> str:
    return "\n\n".join(text for text in texts if text)


def text_part(text: str) -> JsonObject:
    return {"type": "text", "text": text}


def image_part(url: str) -> JsonObject:
    return {"type": "image_url", "image_url": {"url": url}}


def user_message(parts: list[JsonObject], role: str = "user") -> JsonObject | None:
    """None for nothing to say; only text collapses to one string, which every server takes."""
    if not parts:
        return None
    if all(part["type"] == "text" for part in parts):
        texts = [part["text"] for part in parts]
        return {"role": role, "content": join([text for text in texts if isinstance(text, str)])}
    content: list[JsonValue] = list(parts)
    return {"role": role, "content": content}


def tool_call(call_id: str, name: str, arguments: str) -> JsonObject:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": arguments},
    }


def assistant_message(text: str, calls: list[JsonObject]) -> JsonObject:
    if calls:
        tool_calls: list[JsonValue] = list(calls)
        return {"role": "assistant", "content": text or None, "tool_calls": tool_calls}
    return {"role": "assistant", "content": text}


def tool_message(call_id: str, text: str, images: list[str]) -> JsonObject:
    return {
        "role": "tool",
        "tool_call_id": call_id,
        "content": text or (IMAGE_BELOW if images else ""),
    }


def function_tool(name: str, description: str, parameters: JsonValue) -> JsonObject:
    return {
        "type": "function",
        "function": {"name": name, "description": description, "parameters": parameters},
    }


def tool_choice(name: str) -> JsonObject:
    return {"type": "function", "function": {"name": name}}


def stream_options(body: JsonObject, stream: bool) -> None:
    body["stream"] = stream
    if stream:
        body["stream_options"] = {"include_usage": True}
