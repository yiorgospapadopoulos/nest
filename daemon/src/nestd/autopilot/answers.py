"""What Nest answers in the user's place while a run is on: the agent's recommended option,
the plan as it is, and every permission except what stays blocked: removing a worktree,
and git writes unless the user lets agents push (D160).
"""

from collections.abc import Mapping
from datetime import datetime

from pydantic import JsonValue

from nestd.autopilot.models import AutopilotDecision, DecisionOption
from nestd.providers.base import Question, QuestionOption, QuestionRequest
from nestd.providers.git_guard import tool_writes

GUARDED_REASON = "Autopilot leaves pushes, pull requests and removing worktrees to the user."
WORKTREE_REASON = "Autopilot leaves removing worktrees to the user."
NO_OPTIONS_ANSWER = "Use your best judgement; nobody is here to answer."
RECOMMENDED_REASON = "The agent recommended it"
FIRST_OPTION_REASON = "The agent gave no recommendation, so Autopilot took the first option."
NO_OPTIONS_REASON = "The agent gave no options, so Autopilot told it to use its best judgement."
DENIED_ANSWER = "Denied"
# A plan's text a decision keeps.
DETAIL_CHARS = 4000


def blocked(tool: str, tool_input: Mapping[str, object], *, can_push: bool) -> bool:
    return tool_writes(tool, tool_input, pushes=not can_push, worktrees=True)


def refusal(*, can_push: bool) -> str:
    return WORKTREE_REASON if can_push else GUARDED_REASON


def _pick(question: Question) -> QuestionOption | None:
    for option in question.options:
        if option.recommended:
            return option
    return question.options[0] if question.options else None


def chosen(question: Question) -> str:
    option = _pick(question)
    return NO_OPTIONS_ANSWER if option is None else option.label


def answers(request: QuestionRequest) -> dict[str, str]:
    return {question.question: chosen(question) for question in request.questions}


def plan_title(plan: str) -> str:
    first = next((line.strip(" #") for line in plan.splitlines() if line.strip(" #")), "")
    return first or "The plan"


def question_decision(question: Question, at: datetime) -> AutopilotDecision:
    picked = _pick(question)
    return AutopilotDecision(
        kind="question",
        title=question.question,
        answer=chosen(question),
        at=at,
        options=[
            DecisionOption(label=o.label, description=o.description, picked=o is picked)
            for o in question.options
        ],
        reason=_question_reason(picked),
    )


def _question_reason(picked: QuestionOption | None) -> str:
    if picked is None:
        return NO_OPTIONS_REASON
    if not picked.recommended:
        return FIRST_OPTION_REASON
    if picked.description:
        return f"{RECOMMENDED_REASON}: {picked.description}"
    return f"{RECOMMENDED_REASON}."


def plan_decision(plan: str, at: datetime) -> AutopilotDecision:
    detail = plan if len(plan) <= DETAIL_CHARS else f"{plan[:DETAIL_CHARS].rstrip()}..."
    return AutopilotDecision(
        kind="plan", title=plan_title(plan), answer="Approved", at=at, detail=detail or None
    )


def permission_decision(
    title: str, *, denied: bool, reason: str | None, at: datetime
) -> AutopilotDecision:
    """`reason` is why the engine asked or, for a denied call, why Nest refused."""
    if denied:
        return AutopilotDecision(
            kind="denied", title=title, answer=DENIED_ANSWER, at=at, reason=reason
        )
    return AutopilotDecision(kind="allowed", title=title, answer="Allowed", at=at, reason=reason)


def stored_question(raw: JsonValue) -> Question | None:
    """A question as an approval holds it (`sessions.prompts`)."""
    if not isinstance(raw, dict) or not isinstance(raw.get("question"), str):
        return None
    options = raw.get("options")
    return Question(
        question=str(raw["question"]),
        header=None,
        multi_select=False,
        options=tuple(
            QuestionOption(
                label=str(o["label"]),
                description=_text(o.get("description")),
                recommended=o.get("recommended") is True,
            )
            for o in (options if isinstance(options, list) else [])
            if isinstance(o, dict) and "label" in o
        ),
    )


def _text(value: JsonValue | None) -> str | None:
    return value if isinstance(value, str) else None
