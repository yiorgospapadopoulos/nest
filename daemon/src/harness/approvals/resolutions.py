"""The API's resolve request, checked against the kind of item it resolves."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, JsonValue

from harness.approvals.models import Approval, ApprovalKind
from harness.errors import InvalidInputError


class ResolveApproval(BaseModel):
    """Permission: `behavior`, optional `message`, and `always` to allow the tool for the
    rest of the session. Question: `answers` (question text to the chosen label or free
    text; a list for several choices) or `dismiss` with an optional `message`.
    """

    model_config = ConfigDict(extra="forbid")

    behavior: Literal["allow", "deny"] | None = None
    message: str | None = None
    always: bool = False
    answers: dict[str, str | list[str]] | None = None
    dismiss: bool = False


def resolution_for(approval: Approval, body: ResolveApproval) -> dict[str, JsonValue]:
    if approval.kind is ApprovalKind.PERMISSION:
        return _permission(body)
    if approval.kind is ApprovalKind.QUESTION:
        return _question(approval, body)
    msg = "reviews are resolved with the session's approve, reject or feedback actions"
    raise InvalidInputError(msg)


def _permission(body: ResolveApproval) -> dict[str, JsonValue]:
    if body.behavior is None or body.answers is not None or body.dismiss:
        msg = "a permission is resolved with a behavior (allow or deny) only"
        raise InvalidInputError(msg)
    return {"behavior": body.behavior, "message": body.message, "always": body.always}


def _question(approval: Approval, body: ResolveApproval) -> dict[str, JsonValue]:
    if body.behavior is not None:
        msg = "a question takes answers or dismiss, not a behavior"
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
