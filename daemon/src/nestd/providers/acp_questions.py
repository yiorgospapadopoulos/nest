"""Questions to the user on an ACP engine (B112): ACP v1 has no request for them, so every
ACP run that takes Nest's tools gets `ask_user` on the `nest` MCP server.

Its input has the shape of Claude Code's AskUserQuestion, and it goes through the run's
question handler as AskUserQuestion does (`claude_questions`), so the same card shows in
Needs you and the user can always type an answer of their own. The call waits until the
user answers, for as long as Claude's questions wait, or less where the engine gives up on
a tool call sooner (`AcpEngine.mcp_tool_timeout`): the question is then withdrawn and the
model told so, rather than left in Needs you with nobody waiting for its answer.
"""

import asyncio
import json
from datetime import timedelta

from pydantic import JsonValue

from nestd.providers.base import AgentTool, ApprovalHandler, ToolRefusedError
from nestd.providers.claude_questions import (
    DISMISSED_REASON,
    QUESTION_TIMEOUT_SECONDS,
    parse_questions,
)

ASK_USER = "ask_user"
QUESTION_WAIT = timedelta(seconds=QUESTION_TIMEOUT_SECONDS)
# The question is withdrawn this long before the engine stops waiting for the tool.
MARGIN = timedelta(seconds=30)
NO_QUESTIONS = "Ask at least one question, each with its text."
NOT_ANSWERED = (
    "The user did not answer in time, so the question was withdrawn. Go on without the "
    "answer where you can, or ask again later."
)
DESCRIPTION = (
    "Ask the user one to four questions with choices and wait for the answers. Use it when "
    "you need the user's decision or preference to go on. The user can always type an "
    'answer of their own instead. Put "(Recommended)" at the end of the label of the option '
    "you suggest."
)
_OPTION: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "label": {"type": "string", "description": "The choice, in one to five words."},
        "description": {"type": "string", "description": "What choosing it means."},
    },
    "required": ["label", "description"],
}
_QUESTION: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "question": {"type": "string", "description": "The whole question."},
        "header": {"type": "string", "description": "A very short label, at most 12 letters."},
        "options": {"type": "array", "minItems": 2, "maxItems": 4, "items": _OPTION},
        "multiSelect": {
            "type": "boolean",
            "description": "True when the user may choose more than one option.",
        },
    },
    "required": ["question", "header", "options", "multiSelect"],
}
SCHEMA: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "questions": {"type": "array", "minItems": 1, "maxItems": 4, "items": _QUESTION}
    },
    "required": ["questions"],
}


def ask_user_tool(handler: ApprovalHandler, engine_limit: timedelta) -> AgentTool:
    """The run's `ask_user`, answered through `handler`; `engine_limit` is how long the
    engine waits for one MCP tool call.
    """
    wait = min(QUESTION_WAIT, engine_limit - MARGIN)

    async def ask(args: dict[str, JsonValue]) -> str:
        request = parse_questions(args, None)
        if not request.questions or any(not q.question.strip() for q in request.questions):
            raise ToolRefusedError(NO_QUESTIONS)
        try:
            async with asyncio.timeout(wait.total_seconds()):
                answer = await handler.ask(request)
        except TimeoutError as error:
            raise ToolRefusedError(NOT_ANSWERED) from error
        if answer.answers is None:
            raise ToolRefusedError(answer.message or DISMISSED_REASON)
        return answered(answer.answers)

    return AgentTool(ASK_USER, DESCRIPTION, SCHEMA, ask)


def answered(answers: dict[str, str]) -> str:
    """The answers as the model reads them, as Claude Code words AskUserQuestion's."""
    pairs = ", ".join(f"{_quoted(q)}={_quoted(a)}" for q, a in answers.items())
    return f"The user answered your questions: {pairs}. Go on with these answers in mind."


def _quoted(text: str) -> str:
    return json.dumps(text, ensure_ascii=False)
