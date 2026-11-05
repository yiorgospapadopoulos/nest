"""The tool an agent says it is done with, on every engine."""

from collections.abc import Awaitable, Callable

from pydantic import JsonValue

from nestd.providers.base import AgentTool, ToolRefusedError

AUTOPILOT_TOOL = "autopilot_finished"

AUTOPILOT_NOTE = (
    "Autopilot is on: the user is away and will read this chat later, and it goes on until you "
    "finish. Keep writing your short update before each batch of tool calls, for that reader. "
    "Never stop to ask or to offer next steps: decide what the user would most likely want and "
    "carry on. Nest answers your questions for the user, so call those answers Autopilot's "
    "choice, not the user's. "
    "Do not commit, merge, push or open a pull request: those are blocked, so leave the work "
    "in the working tree for the user to review. Do not change where the chat works. "
    f"Only when the whole task is done and checked, call the {AUTOPILOT_TOOL} tool with your "
    "summary: one or two plain lines saying what was asked and what came of it, then short "
    "bullets for what changed, the "
    "choices made and anything the user needs to decide. Then say only that it is finished: "
    "the summary shows in the chat."
)

_DESCRIPTION = (
    "Tell Nest the whole task is done and checked, which ends Autopilot with this summary as "
    "its report. Do not call it while any work remains."
)
_SCHEMA: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "summary": {
            "type": "string",
            "description": "Markdown: a line or two on what was asked and done, then bullets.",
        }
    },
    "required": ["summary"],
}


def autopilot_tool(finished: Callable[[str], Awaitable[None]]) -> AgentTool:
    async def handle(args: dict[str, JsonValue]) -> str:
        summary = args.get("summary")
        if not isinstance(summary, str) or not summary.strip():
            msg = "Say in the summary what was done."
            raise ToolRefusedError(msg)
        await finished(summary.strip())
        return "Noted. End your turn now."

    return AgentTool(AUTOPILOT_TOOL, _DESCRIPTION, _SCHEMA, handle)
