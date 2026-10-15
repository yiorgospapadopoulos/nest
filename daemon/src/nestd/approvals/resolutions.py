"""The API's resolve request, checked against the kind of item it resolves."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, JsonValue

from nestd.approvals.models import Approval, ApprovalKind
from nestd.config.models import PlanApprovalMode
from nestd.errors import InvalidInputError


class ResolveApproval(BaseModel):
    """Permission: `behavior`, optional `message`, and `always` to allow the tool for the
    rest of the session. Question: `answers` (question text to the chosen label or free
    text; a list for several choices) or `dismiss` with an optional `message`. Plan:
    `decision` (approve, or keep_planning with an optional `message` for the agent).
    An approved plan continues in `mode`: acceptEdits (the default), default, or auto with
    a model that supports it. Merge: `dismiss` only; merging goes through the session's
    merge action.
    """

    model_config = ConfigDict(extra="forbid")

    behavior: Literal["allow", "deny"] | None = None
    message: str | None = None
    always: bool = False
    answers: dict[str, str | list[str]] | None = None
    dismiss: bool = False
    decision: Literal["approve", "keep_planning"] | None = None
    mode: PlanApprovalMode | None = None


def resolution_for(approval: Approval, body: ResolveApproval) -> dict[str, JsonValue]:
    if approval.kind is ApprovalKind.PERMISSION:
        return _permission(body)
    if approval.kind is ApprovalKind.QUESTION:
        return _question(approval, body)
    if approval.kind is ApprovalKind.PLAN:
        return _plan(body)
    if approval.kind is ApprovalKind.MERGE:
        return _merge(body)
    msg = "reviews are resolved with the session's approve or feedback actions"
    raise InvalidInputError(msg)


def _permission(body: ResolveApproval) -> dict[str, JsonValue]:
    if (
        body.behavior is None
        or body.answers is not None
        or body.dismiss
        or body.decision
        or body.mode
    ):
        msg = "a permission is resolved with a behavior (allow or deny) only"
        raise InvalidInputError(msg)
    return {"behavior": body.behavior, "message": body.message, "always": body.always}


def _merge(body: ResolveApproval) -> dict[str, JsonValue]:
    if not body.dismiss or body.behavior or body.answers is not None or body.decision or body.mode:
        msg = "a merge is done with the session's merge action, or dismissed with dismiss"
        raise InvalidInputError(msg)
    return {"dismissed": True}


def _plan(body: ResolveApproval) -> dict[str, JsonValue]:
    if (
        body.decision is None
        or body.behavior is not None
        or body.answers is not None
        or body.dismiss
        or body.always
        or (body.mode is not None and body.decision != "approve")
    ):
        msg = "a plan is resolved with a decision (approve or keep_planning) only"
        raise InvalidInputError(msg)
    if body.decision == "approve":
        return {"decision": "approve", "mode": body.mode or "acceptEdits"}
    note = (body.message or "").strip()
    return {"decision": "keep_planning", "message": note or None}


def _question(approval: Approval, body: ResolveApproval) -> dict[str, JsonValue]:
    if body.behavior is not None or body.decision is not None or body.mode is not None:
        msg = "a question takes answers or dismiss, not a behavior, decision or mode"
        raise InvalidInputError(msg)
    if body.dismiss:
        if body.answers is not None:
            msg = "a question takes answers or dismiss, not both"
            raise InvalidInputError(msg)
        return {"dismissed": True, "message": body.message}
    if body.answers is None:
        msg = "a question takes answers or dismiss"
        raise InvalidInputError(msg)
    answers = {question: _answer(value) for question, value in body.answers.items()}
    expected = _question_texts(approval)
    unknown = sorted(answers.keys() - set(expected))
    if unknown:
        msg = f"unknown questions: {', '.join(unknown)}"
        raise InvalidInputError(msg)
    unanswered = [question for question in expected if not answers.get(question)]
    if unanswered:
        msg = f"unanswered: {', '.join(unanswered)}"
        raise InvalidInputError(msg)
    return {"answers": dict(answers)}


def _answer(value: str | list[str]) -> str:
    """Several choices are joined with ", ", as the agent expects."""
    choices = [value] if isinstance(value, str) else value
    return ", ".join(choice.strip() for choice in choices if choice.strip())


def _question_texts(approval: Approval) -> list[str]:
    questions = approval.payload.get("questions")
    if not isinstance(questions, list):
        return []
    return [str(q["question"]) for q in questions if isinstance(q, dict) and "question" in q]
