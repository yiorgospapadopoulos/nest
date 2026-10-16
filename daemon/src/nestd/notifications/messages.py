"""What a notification says and where tapping it leads, whatever the channel."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import get_args
from urllib.parse import quote

from pydantic import JsonValue

from nestd.notifications.notifier import NotifyKind

_LABELS: dict[str, str] = {
    "needs_approval": "Needs approval",
    "question": "Question",
    "review_ready": "Ready for review",
    "failed": "Failed",
    "finished": "Finished",
    "ci_failed": "Checks failed",
    "ready_to_merge": "Ready to merge",
    "stuck": "Stuck",
    "pixie_report": "Report",
    "usage_limit": "Usage limit",
}
# Items that wait in the inbox open it; the rest open their chat.
_INBOX_KINDS = frozenset(
    {"needs_approval", "question", "review_ready", "ci_failed", "ready_to_merge", "stuck"}
)
# The agent is blocked until the user answers.
_URGENT_KINDS = frozenset({"needs_approval", "question"})


@dataclass(frozen=True)
class Notice:
    kind: str
    title: str
    body: str
    # A path inside the PWA, such as "/inbox" or "/chat/<session id>".
    url: str
    # Notifications with the same tag replace each other, so one session shows once.
    tag: str
    urgent: bool

    def web_payload(self) -> dict[str, str]:
        return {"title": self.title, "body": self.body, "url": self.url, "tag": self.tag}


TEST_NOTICE = Notice(
    kind="test",
    title="Nest",
    body="Notifications work on this device.",
    url="/account",
    tag="nest-test",
    urgent=False,
)


def notice_from_event(payload: Mapping[str, JsonValue]) -> Notice | None:
    """The notice for a `notify` event payload, or None if it is not one Nest sends."""
    kind = payload.get("kind")
    session_id = payload.get("session_id")
    repo = payload.get("repo")
    title = payload.get("title")
    text = payload.get("text")
    if (
        kind not in get_args(NotifyKind.__value__)
        or not isinstance(kind, str)
        or not isinstance(session_id, str)
        or not isinstance(repo, str)
        or not isinstance(title, str)
        or not isinstance(text, str)
    ):
        return None
    if kind == "pixie_report":
        return _report_notice(payload, title)
    url = "/inbox" if kind in _INBOX_KINDS else f"/chat/{quote(session_id, safe='')}"
    where = repo
    pixie_id = payload.get("pixie_id")
    if isinstance(pixie_id, str):
        # A pixie's chat opens on its page and is named after it (D072); its title is the
        # pixie's name, so the body leaves it out.
        if kind not in _INBOX_KINDS:
            url = f"/pixie/{quote(pixie_id, safe='')}"
        name = payload.get("pixie_name")
        where = name if isinstance(name, str) else "Pixie"
        title = ""
    return Notice(
        kind=kind,
        title=f"{_LABELS[kind]} · {where}",
        body=f"{title}: {text}" if title else text,
        url=url,
        tag=f"session-{session_id}",
        urgent=kind in _URGENT_KINDS,
    )


def _report_notice(payload: Mapping[str, JsonValue], title: str) -> Notice | None:
    """A pixie's report (B42): titled with the pixie, the report's title as the body; it
    opens the pixie, and one that needs action is urgent.
    """
    pixie_id = payload.get("pixie_id")
    report_id = payload.get("report_id")
    if not isinstance(pixie_id, str) or not isinstance(report_id, str):
        return None
    name = payload.get("pixie_name")
    return Notice(
        kind="pixie_report",
        title=name if isinstance(name, str) else "Pixie",
        body=title,
        url=f"/pixie/{quote(pixie_id, safe='')}",
        tag=f"pixie-report-{report_id}",
        urgent=payload.get("severity") == "action",
    )
