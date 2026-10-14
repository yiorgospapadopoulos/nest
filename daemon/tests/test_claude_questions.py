from typing import Any

from claude_agent_sdk import PermissionResultAllow
from claude_agent_sdk.types import HookInput

from nestd.providers.base import (
    PermissionDecision,
    PermissionRequest,
    PlanDecision,
    PlanRequest,
    Question,
    QuestionAnswer,
    QuestionOption,
    QuestionRequest,
)
from nestd.providers.claude_questions import QuestionBridge, parse_questions

# Shaped like a real AskUserQuestion call.
TOOL_INPUT: dict[str, Any] = {
    "questions": [
        {
            "question": "Which data structure should the planner use?",
            "header": "Data Structure",
            "options": [
                {"label": "DAG (Recommended)", "description": "Tasks with dependencies"},
                {"label": "Tree", "description": "Strict hierarchy"},
            ],
            "multiSelect": False,
        }
    ]
}


class AnsweringHandler:
    def __init__(self, answer: QuestionAnswer) -> None:
        self.answer = answer
        self.requests: list[QuestionRequest] = []

    async def decide(self, request: PermissionRequest) -> PermissionDecision:
        raise AssertionError("questions must not become permission prompts")

    async def ask(self, request: QuestionRequest) -> QuestionAnswer:
        self.requests.append(request)
        return self.answer

    async def review_plan(self, request: PlanRequest) -> PlanDecision:
        raise AssertionError("questions must not become plans")


def pre_tool_use(tool_input: dict[str, Any], tool_use_id: str = "toolu_q") -> HookInput:
    return {
        "hook_event_name": "PreToolUse",
        "session_id": "sdk-1",
        "transcript_path": "/sessions/t.jsonl",
        "cwd": "/repo",
        "tool_name": "AskUserQuestion",
        "tool_input": tool_input,
        "tool_use_id": tool_use_id,
    }


def test_parse_questions_marks_the_recommended_option() -> None:
    request = parse_questions(TOOL_INPUT, "toolu_q")

    assert request == QuestionRequest(
        tool_use_id="toolu_q",
        questions=(
            Question(
                question="Which data structure should the planner use?",
                header="Data Structure",
                multi_select=False,
                options=(
                    QuestionOption("DAG", "Tasks with dependencies", recommended=True),
                    QuestionOption("Tree", "Strict hierarchy"),
                ),
            ),
        ),
    )


def test_parse_questions_tolerates_odd_input() -> None:
    odd = {
        "questions": [
            "not a question",
            {"question": "Free?", "options": [{"label": "A (recommended) "}, "junk", {}]},
            {"question": "Many?", "multiSelect": True, "header": 3},
        ]
    }

    request = parse_questions(odd, None)

    assert request.questions == (
        Question("Free?", None, (QuestionOption("A", None, recommended=True),), False),
        Question("Many?", None, (), True),
    )
    assert parse_questions({}, None).questions == ()


async def test_the_hook_returns_the_answers_as_updated_input() -> None:
    handler = AnsweringHandler(QuestionAnswer({"Which data structure?": "DAG"}))
    bridge = QuestionBridge(handler)

    output = await bridge.hook(pre_tool_use(TOOL_INPUT), "toolu_q", {"signal": None})

    assert output == {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "permissionDecisionReason": "The user answered in Nest.",
            "updatedInput": {**TOOL_INPUT, "answers": {"Which data structure?": "DAG"}},
        }
    }
    assert handler.requests == [parse_questions(TOOL_INPUT, "toolu_q")]


async def test_a_dismissed_question_denies_the_tool() -> None:
    bridge = QuestionBridge(AnsweringHandler(QuestionAnswer(None, "Not now")))
    default = QuestionBridge(AnsweringHandler(QuestionAnswer(None)))

    output = await bridge.hook(pre_tool_use(TOOL_INPUT), "toolu_q", {"signal": None})
    plain = await default.hook(pre_tool_use(TOOL_INPUT), "toolu_q", {"signal": None})

    assert output == {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": "Not now",
        }
    }
    assert plain["hookSpecificOutput"]["permissionDecisionReason"] == (  # pyright: ignore[reportTypedDictNotRequiredAccess, reportGeneralTypeIssues]
        "The user dismissed the question."
    )


async def test_the_hook_ignores_other_events() -> None:
    bridge = QuestionBridge(AnsweringHandler(QuestionAnswer({})))
    stop: HookInput = {
        "hook_event_name": "Stop",
        "session_id": "s",
        "transcript_path": "/t",
        "cwd": "/",
        "stop_hook_active": False,
    }

    assert await bridge.hook(stop, None, {"signal": None}) == {}


async def test_the_permission_check_never_prompts_and_carries_the_answers() -> None:
    bridge = QuestionBridge(AnsweringHandler(QuestionAnswer({"Q?": "A"})))
    await bridge.hook(pre_tool_use(TOOL_INPUT, "toolu_1"), "toolu_1", {"signal": None})

    answered = bridge.permission(TOOL_INPUT, "toolu_1")
    unknown = bridge.permission(TOOL_INPUT, "toolu_2")
    again = bridge.permission(TOOL_INPUT, "toolu_1")

    assert answered == PermissionResultAllow(updated_input={**TOOL_INPUT, "answers": {"Q?": "A"}})
    assert unknown == PermissionResultAllow(updated_input=TOOL_INPUT)
    assert again == PermissionResultAllow(updated_input=TOOL_INPUT)
