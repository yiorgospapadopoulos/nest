"""The tool an agent says it is done with, on every engine."""

from collections.abc import Awaitable, Callable

from pydantic import JsonValue

from nestd.providers.base import AgentTool, ToolRefusedError

AUTOPILOT_TOOL = "autopilot_finished"

_AUTOPILOT_NOTE = (
    "Autopilot is on: the user is away and will read this chat later, and it goes on until you "
    "finish. Keep writing your short update before each batch of tool calls, for that reader. "
    "Never stop to ask or to offer next steps: decide what the user would most likely want and "
    "carry on. Nest answers your questions for the user, so call those answers Autopilot's "
    "choice, not the user's. "
    "Use git as the task needs, but never merge into the project's default branch unless the "
    "task says so. {blocked} "
    f"Only when the whole task is done and checked, call the {AUTOPILOT_TOOL} tool with your "
    "summary: one or two plain lines saying what was asked and what came of it, then short "
    "bullets for what changed, the "
    "choices made and anything the user needs to decide. Then say only that it is finished: "
    "the summary shows in the chat."
)
_NO_PUSH_NOTE = (
    "Pushing, opening or merging a pull request and removing a worktree are blocked: those "
    "stay with the user."
)
_NO_REMOVAL_NOTE = "Removing a worktree is blocked: that stays with the user."

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


def autopilot_note(*, can_push: bool) -> str:
    return _AUTOPILOT_NOTE.replace("{blocked}", _NO_REMOVAL_NOTE if can_push else _NO_PUSH_NOTE)


def autopilot_tool(finished: Callable[[str], Awaitable[None]]) -> AgentTool:
    async def handle(args: dict[str, JsonValue]) -> str:
        summary = args.get("summary")
        if not isinstance(summary, str) or not summary.strip():
            msg = "Say in the summary what was done."
            raise ToolRefusedError(msg)
        await finished(summary.strip())
        return "Noted. End your turn now."

    return AgentTool(AUTOPILOT_TOOL, _DESCRIPTION, _SCHEMA, handle)
