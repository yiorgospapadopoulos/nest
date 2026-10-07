from datetime import time

import pytest
from pydantic import JsonValue

from harness.config.models import NotificationKinds, NotificationSettings, QuietHours
from harness.notifications.messages import TEST_NOTICE, Notice, notice_from_event
from harness.notifications.rules import in_quiet_hours, should_send


def event(kind: str = "needs_approval", **changes: JsonValue) -> dict[str, JsonValue]:
    payload: dict[str, JsonValue] = {
        "kind": kind,
        "session_id": "s/1",
        "repo": "harness",
        "title": "Fix login",
        "text": "Approve Bash: npm test",
    }
    payload.update(changes)
    return payload


@pytest.mark.parametrize(
    ("kind", "label", "url", "urgent"),
    [
        ("needs_approval", "Needs approval", "/inbox", True),
        ("question", "Question", "/inbox", True),
        ("review_ready", "Ready for review", "/inbox", False),
        ("failed", "Failed", "/chat/s%2F1", False),
        ("finished", "Finished", "/chat/s%2F1", False),
        # The inbox shows failed checks with "Send to agent", and the merge approval.
        ("ci_failed", "Checks failed", "/inbox", False),
        ("ready_to_merge", "Ready to merge", "/inbox", False),
        # The inbox card offers Interrupt and Send a nudge.
        ("stuck", "Stuck", "/inbox", False),
    ],
)
def test_each_kind_links_to_where_it_is_handled(
    kind: str, label: str, url: str, urgent: bool
) -> None:
    notice = notice_from_event(event(kind))

    assert notice is not None
    assert notice == Notice(
        kind=kind,
        title=f"{label} · harness",
        body="Fix login: Approve Bash: npm test",
        url=url,
        tag="session-s/1",
        urgent=urgent,
    )
    assert notice.web_payload() == {
        "title": notice.title,
        "body": notice.body,
        "url": url,
        "tag": "session-s/1",
    }


def test_a_missing_title_leaves_only_the_text() -> None:
    notice = notice_from_event(event(title=""))

    assert notice is not None
    assert notice.body == "Approve Bash: npm test"


@pytest.mark.parametrize(
    "payload",
    [
        event("unknown"),
        event(session_id=None),
        event(repo=3),
        event(text=None),
        event(title=None),
    ],
)
def test_malformed_events_give_no_notice(payload: dict[str, JsonValue]) -> None:
    assert notice_from_event(payload) is None


def test_the_test_notice_opens_the_account_tab() -> None:
    assert TEST_NOTICE.url == "/account"
    assert TEST_NOTICE.kind == "test"


@pytest.mark.parametrize(
    ("start", "end", "now", "quiet"),
    [
        ("22:00", "07:00", time(23, 30), True),
        ("22:00", "07:00", time(6, 59), True),
        ("22:00", "07:00", time(7, 0), False),
        ("22:00", "07:00", time(21, 59), False),
        ("22:00", "07:00", time(22, 0), True),
        ("13:00", "14:00", time(13, 30), True),
        ("13:00", "14:00", time(14, 0), False),
        ("13:00", "14:00", time(12, 0), False),
    ],
)
def test_quiet_hours_may_wrap_past_midnight(start: str, end: str, now: time, quiet: bool) -> None:
    assert in_quiet_hours(QuietHours(start=start, end=end), now) is quiet


def test_no_quiet_hours_is_never_quiet() -> None:
    assert in_quiet_hours(None, time(3, 0)) is False


def test_should_send_needs_the_kind_enabled_and_no_quiet_hours() -> None:
    settings = NotificationSettings(kinds=NotificationKinds(finished=False))

    assert should_send(settings, "failed", time(12, 0))
    assert not should_send(settings, "finished", time(12, 0))
    quiet = settings.model_copy(update={"quiet_hours": QuietHours(start="11:00", end="13:00")})
    assert not should_send(quiet, "failed", time(12, 0))
