"""The line a called pixie shows in the chat that called it (B133): a short update at a
real milestone, or that it waits for the user. A helper's text does not reach the chat while
it works in the background, so this is a tool, on every engine: the chat's run offers it to
the pixies that are its own subagents, and a called session has it for its own call.

A line is a notice in the chat, nothing more: the chat's agent does not read it and no turn
starts.
"""

from collections.abc import Awaitable, Callable, Sequence

from pydantic import JsonValue

from nestd.providers.base import AgentTool, ToolRefusedError
from nestd.tracking.steps import one_line

TELL_CHAT_TOOL = "tell_chat"
LINE_CHARS = 200
SHOWN = "Shown in the chat. Go on with your work."
EMPTY_LINE = "Say something in `text`."
DESCRIPTION = (
    "Only for a pixie doing a job another chat called it for: show one short line in that"
    " chat, for the user. Nothing reads it for you and it wakes nobody; your report still"
    " comes at the end. When a job has several stages or takes more than a minute, send it"
    ' each time a stage ends, saying what is done and what comes next ("Backend done, starting'
    ' web"). A job of one quick step sends none. When you cannot'
    " go on without the user's decision, set `waiting` with the question in `text`: the user"
    " is notified. Then end your work, with the same question in your report."
)
_TEXT: dict[str, JsonValue] = {"type": "string", "description": "One short line."}
_WAITING: dict[str, JsonValue] = {
    "type": "boolean",
    "description": "You stopped for the user's decision.",
}

# The pixie's slug when the tool names one, the line, and whether it waits for the user.
type Tell = Callable[[str | None, str, bool], Awaitable[None]]


def tell_chat_tool(slugs: Sequence[str], tell: Tell) -> AgentTool:
    """`slugs` are the pixies that may be speaking, when the run's agent cannot be told
    from the call itself; a called session speaks for its one pixie.
    """
    properties: dict[str, JsonValue] = {"text": _TEXT, "waiting": _WAITING}
    required: list[JsonValue] = ["text"]
    if slugs:
        properties["pixie"] = {
            "type": "string",
            "enum": list[JsonValue](slugs),
            "description": "Your own slug.",
        }
        required.append("pixie")
    schema: dict[str, JsonValue] = {
        "type": "object",
        "properties": properties,
        "required": required,
    }

    async def handle(args: dict[str, JsonValue]) -> str:
        text = args.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ToolRefusedError(EMPTY_LINE)
        slug = args.get("pixie")
        await tell(
            slug if isinstance(slug, str) else None,
            one_line(" ".join(text.split()), LINE_CHARS),
            args.get("waiting") is True,
        )
        return SHOWN

    return AgentTool(TELL_CHAT_TOOL, DESCRIPTION, schema, handle)
