"""The text views a pixie's tools give of chats, prompts, transcripts and pull requests."""

from datetime import UTC, datetime
from pathlib import Path

from pydantic import JsonValue

from nestd.approvals.models import Approval, ApprovalKind, ApprovalStatus
from nestd.events import types
from nestd.events.models import Event
from nestd.pixies import digest
from nestd.pixies.digest import Entry
from nestd.prs.models import PrChecks, PrStatus
from nestd.sessions.models import Session, SessionState
from nestd.stuck.models import StuckFlag

NOW = datetime(2026, 10, 14, tzinfo=UTC)


def chat(**fields: object) -> Session:
    values: dict[str, object] = {
        "id": "s1",
        "repo": "web",
        "title": "Fix\nthe bug",
        "prompt": "p",
        "mode": "worktree",
        "cwd": None,
        "model": None,
        "effort": None,
        "permission_mode": "default",
        "provider": "fake",
        "state": SessionState.IDLE,
        "worktree_path": None,
        "branch": None,
        "provider_session_id": None,
        "created_at": NOW,
        "updated_at": NOW,
        "last_error": None,
    }
    values.update(fields)
    return Session.model_validate(values)


def approval(kind: ApprovalKind, payload: dict[str, JsonValue]) -> Approval:
    return Approval(
        id="a1",
        session_id="s1",
        repo="web",
        title="t",
        kind=kind,
        status=ApprovalStatus.PENDING,
        payload=payload,
        resolution=None,
        created_at=NOW,
        resolved_at=None,
    )


def pr(**fields: object) -> PrStatus:
    values: dict[str, object] = {
        "number": 3,
        "url": "https://github.com/u/web/pull/3",
        "title": "Fix",
        "state": "merged",
        "checks": PrChecks(state="none", passed=0, failed=0, pending=0, items=[]),
        "mergeable": None,
        "merge_state": None,
        "review_decision": None,
        "head_sha": None,
        "created_at": None,
        "changed_at": NOW,
        "updated_at": NOW,
    }
    values.update(fields)
    return PrStatus.model_validate(values)


def test_status_names_what_the_user_sees() -> None:
    idle = chat()

    assert digest.status(idle, [ApprovalKind.REVIEW]) == "ready for review"
    assert digest.status(idle, [ApprovalKind.MERGE]) == "ready to merge"
    assert digest.status(idle, [ApprovalKind.PLAN, ApprovalKind.REVIEW]) == "waiting on a plan"
    assert digest.status(chat(state=SessionState.FAILED), [ApprovalKind.REVIEW]) == "failed"
    assert digest.status(idle, []) == "idle"


def test_a_title_is_one_line_without_fences() -> None:
    assert digest.title(chat(title="```Fix``` it\nnow")) == "'''Fix''' it"


def test_a_line_per_chat() -> None:
    mine = chat(started_by_pixie="p1", pr=pr())

    assert digest.session_line(mine, [], "p1") == (
        "s1 | Fix | web | idle | started by you | PR #3 merged"
    )
    assert digest.session_line(mine, [], "p2") == "s1 | Fix | web | idle | PR #3 merged"


def test_details_of_a_chat() -> None:
    other = chat(
        started_by_pixie="p2",
        last_error="disk\nfull",
        stuck=StuckFlag(reason="silent", since=NOW, details="No output for 12 minutes"),
        pr_url="https://github.com/u/web/pull/3",
    )
    mine = chat(started_by_pixie="p1", worktree_path=Path("/w"), branch="agent/x", model="opus")

    other_text = digest.session_details(other, [], "p1")
    mine_text = digest.session_details(mine, [], "p1")

    assert "Started by: another pixie" in other_text
    assert "Work: in place in the project's folder" in other_text
    assert "Error: disk" in other_text
    assert "Looks stuck: No output for 12 minutes" in other_text
    assert "Pull request: https://github.com/u/web/pull/3" in other_text
    assert "Started by: you" in mine_text
    assert "Work: its own worktree on branch agent/x" in mine_text
    assert "Model: opus, effort default" in mine_text


def test_a_pull_request_without_failing_checks() -> None:
    text = digest.pr_text(chat(pr_url="u", pr=pr(mergeable=False)))

    assert text.splitlines()[2:] == [
        "Checks: none (0 passed, 0 failed, 0 pending)",
        "Review: none required",
        "Mergeable: no (unknown)",
    ]


def test_each_kind_of_prompt_in_one_line() -> None:
    session = chat(started_by_pixie="p1")
    cases: list[tuple[ApprovalKind, dict[str, JsonValue]]] = [
        (ApprovalKind.PERMISSION, {"tool": "Bash", "input": {"command": "rm -rf build"}}),
        (ApprovalKind.PERMISSION, {"tool": "Read", "input": "odd"}),
        (ApprovalKind.QUESTION, {"questions": [{"question": "Ready?"}, "odd"]}),
        (ApprovalKind.QUESTION, {"questions": "odd"}),
        (ApprovalKind.PLAN, {"plan": "1. Read\n2. Write"}),
        (ApprovalKind.REVIEW, {}),
        (ApprovalKind.MERGE, {}),
    ]
    lines = [
        digest.approval_line(approval(kind, payload), session, "p1") for kind, payload in cases
    ]

    assert lines[0] == '- a1: permission in chat s1 "Fix" (web, started by you): Bash rm -rf build'
    assert [line.split("): ", 1)[1] for line in lines[1:]] == [
        "Read",
        "Ready?",
        "",
        "1. Read",
        "work ready for the user's review",
        "pull request ready for the user to merge",
    ]


def event(event_id: int, event_type: str, payload: dict[str, JsonValue]) -> Event:
    return Event(id=event_id, type=event_type, ts=NOW, session_id="s1", payload=payload)


def test_transcript_lines_for_each_kind_of_event() -> None:
    found = digest.entries(
        [
            event(1, types.SESSION_USER_MESSAGE, {"text": "Do it", "from_pixie": "p1"}),
            event(2, types.SESSION_STATE, {"state": "failed", "error": "no\nspace"}),
            event(3, types.SESSION_STATE, {"state": "running", "error": None}),
            event(4, types.APPROVAL_CREATED, {"approval": {"kind": "plan", "id": "a1"}}),
            event(5, types.APPROVAL_CREATED, {"approval": "odd"}),
            event(6, types.SESSION_NOTICE, {"kind": "compacted", "text": "Compacted"}),
            event(7, types.SESSION_MESSAGE, {"blocks": [{"type": "tool_use", "name": "Glob"}]}),
            event(8, types.SESSION_DELTA, {"text": "x"}),
        ]
    )

    assert found == [
        Entry(1, "User (from a pixie): Do it"),
        Entry(2, "State: failed: no space"),
        Entry(4, "Waiting on plan (approval a1)"),
        Entry(6, "Notice: Compacted"),
        Entry(7, "Tool Glob"),
    ]


def test_a_long_text_is_cut() -> None:
    (entry,) = digest.entries([event(1, types.SESSION_USER_MESSAGE, {"text": "a" * 600})])

    assert entry.text == "User: " + "a" * (digest.USER_CHARS - 1) + "…"


def test_pages_end_with_whole_events_when_they_can() -> None:
    found = [Entry(1, "a"), Entry(2, "b"), Entry(2, "c"), Entry(3, "d")]

    assert digest.page(found, 4) == (found, None)
    assert digest.page(found, 2) == ([Entry(1, "a")], 1)
    assert digest.page(found, 3) == (found[:3], 2)
    # One event longer than a page: the rest of it is skipped.
    assert digest.page([Entry(5, "x"), Entry(5, "y")], 1) == ([Entry(5, "x")], 5)
