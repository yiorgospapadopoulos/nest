"""AskUserQuestion through the approval queue in every permission mode (D018).

A PreToolUse hook runs for every tool call, unlike `can_use_tool`, which is skipped in
bypassPermissions mode. The hook holds the call until the user answers, then allows it
with the answers added to its input. The permission check never prompts for the tool; if
the engine consults it after the hook, it passes the remembered answers along.
"""

import re
from typing import Any, cast

from claude_agent_sdk import PermissionResultAllow
from claude_agent_sdk.types import HookContext, HookInput, HookJSONOutput

from harness.providers.base import ApprovalHandler, Question, QuestionOption, QuestionRequest

ASK_USER_QUESTION = "AskUserQuestion"
# The engine stops waiting for a hook after this long; questions can wait for days.
QUESTION_TIMEOUT_SECONDS = 7 * 24 * 60 * 60
ANSWERED_REASON = "The user answered in harness."
DISMISSED_REASON = "The user dismissed the question."

_RECOMMENDED = re.compile(r"\s*\(recommended\)\s*$", re.IGNORECASE)


def parse_questions(tool_input: dict[str, Any], tool_use_id: str | None) -> QuestionRequest:
    """The tool's questions; Claude marks its preferred option with "(Recommended)"."""
    return QuestionRequest(
        questions=tuple(_question(q) for q in _dicts(tool_input.get("questions"))),
        tool_use_id=tool_use_id,
    )


class QuestionBridge:
    def __init__(self, handler: ApprovalHandler) -> None:
        self._handler = handler
        # Answers by tool use id, for a permission check that follows the hook.
        self._answers: dict[str, dict[str, str]] = {}

    async def hook(
        self, input_data: HookInput, tool_use_id: str | None, context: HookContext
    ) -> HookJSONOutput:
        if input_data["hook_event_name"] != "PreToolUse":
            return {}
        tool_input = input_data["tool_input"]
        call_id = input_data["tool_use_id"]
        answer = await self._handler.ask(parse_questions(tool_input, call_id))
        if answer.answers is None:
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": answer.message or DISMISSED_REASON,
                }
            }
        self._answers[call_id] = answer.answers
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
                "permissionDecisionReason": ANSWERED_REASON,
                "updatedInput": {**tool_input, "answers": answer.answers},
            }
        }

    def permission(
        self, tool_input: dict[str, Any], tool_use_id: str | None
    ) -> PermissionResultAllow:
        answers = self._answers.pop(tool_use_id or "", None)
        if answers is None:
            return PermissionResultAllow(updated_input=tool_input)
        return PermissionResultAllow(updated_input={**tool_input, "answers": answers})


def _dicts(value: object) -> list[dict[str, Any]]:
    """The objects in a JSON list; anything else in the input is ignored."""
    if not isinstance(value, list):
        return []
    return [cast(dict[str, Any], v) for v in cast(list[object], value) if isinstance(v, dict)]


def _question(raw: dict[str, Any]) -> Question:
    header = raw.get("header")
    return Question(
        question=str(raw.get("question", "")),
        header=header if isinstance(header, str) else None,
        options=tuple(_option(o) for o in _dicts(raw.get("options")) if "label" in o),
        multi_select=raw.get("multiSelect") is True,
    )


def _option(raw: dict[str, Any]) -> QuestionOption:
    label = str(raw["label"])
    clean = _RECOMMENDED.sub("", label)
    description = raw.get("description")
    return QuestionOption(
        label=clean,
        description=description if isinstance(description, str) else None,
        recommended=clean != label,
    )
