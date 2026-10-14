from datetime import UTC, datetime

import pytest
from pydantic import JsonValue, ValidationError

from harness.approvals.models import Approval, ApprovalKind, ApprovalStatus
from harness.approvals.resolutions import ResolveApproval, resolution_for
from harness.errors import InvalidInputError

QUESTIONS: dict[str, JsonValue] = {
    "questions": [
        {"question": "Which structure?", "header": "Data", "multi_select": False, "options": []},
        {"question": "Which checks?", "header": None, "multi_select": True, "options": []},
    ]
}


def approval(kind: ApprovalKind, payload: dict[str, JsonValue] | None = None) -> Approval:
    return Approval(
        id="a1",
        session_id="s1",
        repo="repo",
        title="t",
        kind=kind,
        status=ApprovalStatus.PENDING,
        payload=payload or {},
        resolution=None,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        resolved_at=None,
    )


def body(**fields: object) -> ResolveApproval:
    return ResolveApproval.model_validate(fields)


def test_permission_resolutions() -> None:
    item = approval(ApprovalKind.PERMISSION)

    assert resolution_for(item, body(behavior="allow")) == {
        "behavior": "allow",
        "message": None,
        "always": False,
    }
    assert resolution_for(item, body(behavior="deny", message="no", always=True)) == {
        "behavior": "deny",
        "message": "no",
        "always": True,
    }


@pytest.mark.parametrize(
    "fields",
    [
        {},
        {"behavior": "allow", "answers": {}},
        {"behavior": "allow", "dismiss": True},
        {"behavior": "allow", "decision": "approve"},
        {"behavior": "allow", "mode": "auto"},
    ],
)
def test_invalid_permission_resolutions(fields: dict[str, object]) -> None:
    with pytest.raises(InvalidInputError, match="permission"):
        resolution_for(approval(ApprovalKind.PERMISSION), body(**fields))


def test_question_answers_join_multiple_choices() -> None:
    resolution = resolution_for(
        approval(ApprovalKind.QUESTION, QUESTIONS),
        body(answers={"Which structure?": " DAG ", "Which checks?": ["Lint", "Tests"]}),
    )

    assert resolution == {"answers": {"Which structure?": "DAG", "Which checks?": "Lint, Tests"}}


def test_a_question_can_be_dismissed() -> None:
    item = approval(ApprovalKind.QUESTION, QUESTIONS)

    assert resolution_for(item, body(dismiss=True)) == {"dismissed": True, "message": None}
    assert resolution_for(item, body(dismiss=True, message="later")) == {
        "dismissed": True,
        "message": "later",
    }


@pytest.mark.parametrize(
    ("fields", "error"),
    [
        ({}, "answers or dismiss"),
        ({"answers": {"Which structure?": "DAG"}, "dismiss": True}, "answers or dismiss"),
        ({"behavior": "allow", "dismiss": True}, "behavior"),
        ({"answers": {"Which structure?": "DAG"}}, "unanswered: Which checks?"),
        ({"answers": {"Which structure?": "DAG", "Which checks?": "  "}}, "unanswered"),
        ({"answers": {"Which structure?": "DAG", "Which checks?": []}}, "unanswered"),
        (
            {"answers": {"Which structure?": "DAG", "Which checks?": "x", "Extra?": "y"}},
            "unknown questions: Extra?",
        ),
    ],
)
def test_invalid_question_resolutions(fields: dict[str, object], error: str) -> None:
    with pytest.raises(InvalidInputError, match=error):
        resolution_for(approval(ApprovalKind.QUESTION, QUESTIONS), body(**fields))


def test_question_payloads_without_questions_accept_no_answers() -> None:
    item = approval(ApprovalKind.QUESTION, {"questions": "garbled"})

    assert resolution_for(item, body(answers={})) == {"answers": {}}


def test_reviews_use_the_review_actions() -> None:
    with pytest.raises(InvalidInputError, match="approve, reject or feedback"):
        resolution_for(approval(ApprovalKind.REVIEW), body(behavior="allow"))


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        body(surprise=True)
    with pytest.raises(ValidationError):
        body(decision="approve", mode="bypassPermissions")


def test_a_question_takes_no_mode() -> None:
    with pytest.raises(InvalidInputError, match="question"):
        resolution_for(
            approval(ApprovalKind.QUESTION, QUESTIONS),
            body(answers={"Which structure?": "DAG", "Which checks?": "all"}, mode="auto"),
        )


def test_plan_resolutions() -> None:
    item = approval(ApprovalKind.PLAN, {"plan": "# Plan"})

    assert resolution_for(item, body(decision="approve")) == {
        "decision": "approve",
        "mode": "acceptEdits",
    }
    for mode in ("default", "auto", "acceptEdits"):
        assert resolution_for(item, body(decision="approve", mode=mode)) == {
            "decision": "approve",
            "mode": mode,
        }
    assert resolution_for(item, body(decision="keep_planning", message="  more tests ")) == {
        "decision": "keep_planning",
        "message": "more tests",
    }
    assert resolution_for(item, body(decision="keep_planning", message=" ")) == {
        "decision": "keep_planning",
        "message": None,
    }


@pytest.mark.parametrize(
    "fields",
    [
        {},
        {"behavior": "allow"},
        {"decision": "approve", "behavior": "allow"},
        {"decision": "approve", "answers": {}},
        {"decision": "approve", "dismiss": True},
        {"decision": "approve", "always": True},
        {"decision": "keep_planning", "mode": "auto"},
    ],
)
def test_invalid_plan_resolutions(fields: dict[str, object]) -> None:
    with pytest.raises(InvalidInputError, match="plan"):
        resolution_for(approval(ApprovalKind.PLAN), body(**fields))


def test_a_question_takes_no_decision() -> None:
    with pytest.raises(InvalidInputError, match="question"):
        resolution_for(approval(ApprovalKind.QUESTION, QUESTIONS), body(decision="approve"))


def test_a_merge_approval_can_only_be_dismissed() -> None:
    item = approval(ApprovalKind.MERGE, {"number": 7})

    assert resolution_for(item, body(dismiss=True)) == {"dismissed": True}


@pytest.mark.parametrize(
    "fields",
    [
        {},
        {"behavior": "allow"},
        {"decision": "approve"},
        {"dismiss": True, "behavior": "allow"},
        {"dismiss": True, "answers": {}},
        {"dismiss": True, "decision": "approve"},
        {"dismiss": True, "mode": "auto"},
    ],
)
def test_a_merge_is_not_resolved_through_the_queue(fields: dict[str, object]) -> None:
    with pytest.raises(InvalidInputError, match="merge action"):
        resolution_for(approval(ApprovalKind.MERGE), body(**fields))
