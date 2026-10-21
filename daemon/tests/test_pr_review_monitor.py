"""B101: the monitor reads a pull request's review comments; new ones wait in Needs you or
go to the agent on their own.
"""

import logging
from pathlib import Path
from typing import Any

import pytest

from nestd.approvals.models import Approval, ApprovalKind, ApprovalStatus
from nestd.events import types
from nestd.prs.errors import NoReviewCommentsError
from nestd.prs.models import PrReview, ReviewComment
from nestd.prs.reviews import REPLY, parse_reviews
from nestd.sessions.errors import SessionBusyError
from nestd.sessions.models import Session, SessionState
from nestd.storage.db import Database
from tests.fake_runner import pr_json
from tests.fakes import FakeClock
from tests.github_support import fixture, review_threads, thread
from tests.test_pr_monitor import Env


@pytest.fixture
def env(db: Database, clock: FakeClock, tmp_path: Path) -> Env:
    return Env(db, clock, tmp_path)


ONE = review_threads([thread("T1", ("C1", "sam", "Rename this."))], [])
TWO = review_threads(
    [thread("T1", ("C1", "sam", "Rename this.")), thread("T2", ("C2", "ana", "And this."))], []
)


async def opened(env: Env, reviews: str) -> Session:
    session = await env.session()
    env.runner.pr_view = pr_json()
    env.runner.pr_reviews = reviews
    return await env.monitor.refresh(session)


async def asks(env: Env, session_id: str) -> list[Approval]:
    items = await env.approvals.list_approvals()
    return [
        a for a in items if a.session_id == session_id and a.kind is ApprovalKind.REVIEW_COMMENTS
    ]


def comment_ids(approval: Approval) -> list[Any]:
    comments = approval.payload["comments"]
    assert isinstance(comments, list)
    return [c["id"] for c in comments if isinstance(c, dict)]


async def test_review_comments_are_kept_published_and_wait_in_needs_you(env: Env) -> None:
    session = await opened(env, fixture("pr_review_threads"))

    review = session.review
    assert review is not None
    assert [item.id for item in review.items] == [
        "PRRT_kwDOK1a2b85Aaaa1:PRRC_kwDOK1a2b86Bbbb1",
        "PRRT_kwDOK1a2b85Aaaa3:PRRC_kwDOK1a2b86Bbbb5",
        "PRR_kwDOK1a2b86Cccc1",
    ]
    assert (review.sent, review.changes_requested, review.auto_send) == ([], True, False)
    (published,) = await env.events(session.id, types.SESSION_PR_REVIEW)
    assert published == {"review": review.model_dump(mode="json")}
    (ask,) = await asks(env, session.id)
    assert ask.payload == {
        "number": 7,
        "url": "https://github.com/me/repo/pull/7",
        "changes_requested": True,
        "comments": [item.model_dump(mode="json") for item in review.items],
    }
    # One notice, with the other approvals (the merge approval has its own kind).
    assert await env.notices(session.id, "needs_approval") == ["3 review comments on #7"]
    assert env.runner.calls[-1][:3] == ("gh", "api", "graphql")


async def test_nothing_new_changes_nothing(env: Env) -> None:
    session = await opened(env, ONE)

    session = await env.monitor.refresh(session)

    assert len(await env.events(session.id, types.SESSION_PR_REVIEW)) == 1
    (ask,) = await asks(env, session.id)
    assert ask.status is ApprovalStatus.PENDING
    assert await env.notices(session.id, "needs_approval") == ["1 review comment on #7"]


async def test_a_new_comment_replaces_the_ask_and_resolving_all_expires_it(env: Env) -> None:
    session = await opened(env, ONE)

    env.runner.pr_reviews = TWO
    session = await env.monitor.refresh(session)
    first, second = await asks(env, session.id)
    assert first.status is ApprovalStatus.SUPERSEDED
    assert comment_ids(second) == ["T1:C1", "T2:C2"]

    env.runner.pr_reviews = review_threads(
        [
            thread("T1", ("C1", "sam", "x"), resolved=True),
            thread("T2", ("C2", "ana", "y"), resolved=True),
        ],
        [],
    )
    session = await env.monitor.refresh(session)
    assert session.review is not None
    assert session.review.items == []
    assert (await asks(env, session.id))[-1].status is ApprovalStatus.EXPIRED


async def test_a_merged_pull_request_expires_the_ask_and_reads_no_reviews(env: Env) -> None:
    session = await opened(env, ONE)
    calls = len(env.runner.calls)

    env.runner.pr_view = pr_json(state="MERGED")
    session = await env.monitor.refresh(session)

    (ask,) = await asks(env, session.id)
    assert ask.status is ApprovalStatus.EXPIRED
    assert [call[1] for call in env.runner.calls[calls:]] == ["pr"]
    assert session.review is not None


async def test_a_failed_review_read_keeps_the_status_and_what_was_known(
    env: Env, caplog: pytest.LogCaptureFixture
) -> None:
    session = await opened(env, ONE)

    env.runner.pr_reviews = None
    env.runner.pr_view = pr_json(title="Renamed")
    with caplog.at_level(logging.WARNING):
        session = await env.monitor.refresh(session)
    env.runner.pr_reviews = "not json"
    session = await env.monitor.refresh(session)

    assert session.pr is not None
    assert session.pr.title == "Renamed"
    assert session.review is not None
    assert len(session.review.items) == 1
    assert "could not read the reviews of https://github.com/me/repo/pull/7 (CommandError)" in (
        caplog.text
    )
    assert "reach" not in caplog.text


async def test_sending_marks_the_comments_sent_and_resolves_the_ask(env: Env) -> None:
    session = await opened(env, TWO)

    await env.monitor.send_review(session.id)

    ((session_id, text, sender),) = env.sent
    assert session_id == session.id
    assert text.startswith("Review feedback on #7, sent by Nest.")
    assert sender.extra is not None
    feedback = sender.extra["review_feedback"]
    assert isinstance(feedback, dict)
    assert (feedback["number"], feedback["count"]) == (7, 2)
    stored = await env.store.get(session.id)
    assert stored.review is not None
    assert stored.review.sent == ["T1:C1", "T2:C2"]
    assert stored.review.pending() == []
    (ask,) = await asks(env, session.id)
    assert (ask.status, ask.resolution) == (ApprovalStatus.RESOLVED, {"action": "sent"})
    with pytest.raises(NoReviewCommentsError):
        await env.monitor.send_review(session.id)

    # A reply makes its thread wait again.
    env.runner.pr_reviews = review_threads(
        [
            thread("T1", ("C1", "sam", "Rename this."), ("C3", "sam", "Still not done.")),
            thread("T2", ("C2", "ana", "And this.")),
        ],
        [],
    )
    await env.monitor.refresh(stored)
    assert comment_ids((await asks(env, session.id))[-1]) == ["T1:C3"]


async def test_comments_cut_from_a_long_message_wait_in_a_new_ask(env: Env) -> None:
    threads = [thread(f"T{n}", (f"C{n}", "sam", "word " * 3000)) for n in range(3)]
    session = await opened(env, review_threads(threads, []))

    await env.monitor.send_review(session.id)

    stored = await env.store.get(session.id)
    assert stored.review is not None
    waiting = [item.id for item in stored.review.pending()]
    assert waiting
    first, second = await asks(env, session.id)
    assert first.status is ApprovalStatus.SUPERSEDED
    assert (second.status, comment_ids(second)) == (ApprovalStatus.PENDING, waiting)


async def test_comments_can_be_sent_one_at_a_time(env: Env) -> None:
    session = await opened(env, TWO)

    await env.monitor.send_review(session.id, ["T2:C2", "nope"])

    ((_, text, sender),) = env.sent
    assert "ana:" in text
    assert "Rename this." not in text
    assert sender.extra is not None
    feedback = sender.extra["review_feedback"]
    assert isinstance(feedback, dict)
    assert feedback["count"] == 1
    stored = await env.store.get(session.id)
    assert stored.review is not None
    assert stored.review.sent == ["T2:C2"]
    first, second = await asks(env, session.id)
    assert first.status is ApprovalStatus.SUPERSEDED
    assert (second.status, comment_ids(second)) == (ApprovalStatus.PENDING, ["T1:C1"])
    assert second.payload["comments"] is not None
    assert await env.notices(session.id, "needs_approval") == [
        "2 review comments on #7",
        "1 review comment on #7",
    ]

    with pytest.raises(NoReviewCommentsError):
        await env.monitor.send_review(session.id, ["T2:C2", "nope"])
    await env.monitor.send_review(session.id, ["T1:C1"])

    asked = await asks(env, session.id)
    assert [a.status for a in asked] == [ApprovalStatus.SUPERSEDED, ApprovalStatus.RESOLVED]
    assert asked[-1].resolution == {"action": "sent"}


async def test_chosen_comments_go_in_the_pull_requests_order(env: Env) -> None:
    session = await opened(env, TWO)

    await env.monitor.send_review(session.id, ["T2:C2", "T1:C1"])

    ((_, text, _),) = env.sent
    assert text.index("Rename this.") < text.index("And this.")
    (ask,) = await asks(env, session.id)
    assert (ask.status, ask.resolution) == (ApprovalStatus.RESOLVED, {"action": "sent"})


async def test_with_auto_send_new_comments_go_to_the_agent_without_an_ask(env: Env) -> None:
    session = await opened(env, ONE)
    review = session.review
    assert review is not None
    await env.monitor.set_review(session.id, review.model_copy(update={"auto_send": True}))

    env.runner.pr_reviews = TWO
    session = await env.monitor.refresh(await env.store.get(session.id))

    ((_, text, sender),) = env.sent
    assert text.startswith("Review feedback on #7, sent by Nest.")
    assert sender.extra is not None
    feedback = sender.extra["review_feedback"]
    assert isinstance(feedback, dict)
    assert feedback["count"] == 2
    assert session.review is not None
    assert session.review.pending() == []
    assert [a.status for a in await asks(env, session.id)] == [ApprovalStatus.RESOLVED]
    published = await env.events(session.id, types.SESSION_PR_REVIEW)
    assert published[-1] == {"review": session.review.model_dump(mode="json")}


async def test_an_auto_send_that_fails_leaves_the_comments_in_needs_you(env: Env) -> None:
    session = await env.session()
    await env.monitor.set_review(
        session.id, PrReview(items=[], sent=[], changes_requested=False, auto_send=True)
    )
    env.send_failure = SessionBusyError("closing")

    session = await opened_again(env, session)

    assert env.sent == []
    (ask,) = await asks(env, session.id)
    assert ask.status is ApprovalStatus.PENDING


async def opened_again(env: Env, session: Session) -> Session:
    env.runner.pr_view = pr_json()
    env.runner.pr_reviews = ONE
    return await env.monitor.refresh(await env.store.get(session.id))


async def test_a_closed_chat_gets_no_ask(env: Env) -> None:
    session = await env.session()
    await env.store.update(session.id, state=SessionState.CLOSED)

    session = await opened_again(env, session)

    assert session.review is not None
    assert await asks(env, session.id) == []


SUMMARY = {
    "id": "PRR_1",
    "state": "COMMENTED",
    "body": "Please also update the docs.",
    "author": {"login": "sam", "__typename": "User"},
    "url": "https://github.com/me/repo/pull/7#pullrequestreview-1",
    "submittedAt": "2026-10-20T11:00:00Z",
}


async def test_open_review_threads_keep_the_merge_card_away_until_resolved(env: Env) -> None:
    """The case seen live: no checks, mergeable, one unresolved comment."""
    session = await opened(env, ONE)

    # Only the review comments wait, never both.
    assert await env.merges(session.id) == []
    assert [a.status for a in await asks(env, session.id)] == [ApprovalStatus.PENDING]

    # Sent, the thread still blocks until it is resolved on GitHub.
    await env.monitor.send_review(session.id)
    session = await env.monitor.refresh(await env.store.get(session.id))
    assert await env.merges(session.id) == []

    env.runner.pr_reviews = review_threads(
        [thread("T1", ("C1", "sam", "Rename this."), resolved=True)], []
    )
    session = await env.monitor.refresh(session)
    (merge,) = await env.merges(session.id)
    assert merge.status is ApprovalStatus.PENDING

    # Nothing new: no second merge card.
    await env.monitor.refresh(session)
    assert len(await env.merges(session.id)) == 1


async def test_a_merge_card_from_before_is_taken_away_by_one_unchanged_refresh(env: Env) -> None:
    """Seen live: a merge approval made before the hold existed, a sent but unresolved
    thread stored, and a status that does not change.
    """
    session = await opened(env, review_threads([], []))
    (merge,) = await env.merges(session.id)
    held = PrReview(items=parse_reviews_items(ONE), sent=["T1:C1"], changes_requested=False)
    await env.store.set_review(session.id, held)
    env.runner.pr_reviews = ONE
    calls = len(env.runner.calls)

    session = await env.monitor.refresh(await env.store.get(session.id))

    (merge,) = await env.merges(session.id)
    assert merge.status is ApprovalStatus.EXPIRED
    assert merge.resolution == {"reason": "review comments are open on the pull request"}
    # The status and the review read the same as before.
    assert len(env.runner.calls) == calls + 2
    assert len(await env.events(session.id, types.SESSION_PR)) == 1
    assert (await env.store.get(session.id)).review == held
    assert await asks(env, session.id) == []


def parse_reviews_items(output: str) -> list[ReviewComment]:
    return parse_reviews(output).items


async def test_a_new_comment_takes_a_pending_merge_card_away(env: Env) -> None:
    session = await opened(env, review_threads([], []))
    (merge,) = await env.merges(session.id)
    assert merge.status is ApprovalStatus.PENDING

    env.runner.pr_reviews = ONE
    session = await env.monitor.refresh(session)

    (merge,) = await env.merges(session.id)
    assert merge.status is ApprovalStatus.EXPIRED
    assert merge.resolution == {"reason": "review comments are open on the pull request"}


async def test_a_summary_sent_on_its_own_at_the_first_read_lets_the_merge_show(env: Env) -> None:
    session = await env.session()
    await env.monitor.set_auto_send(session.id, True)
    env.runner.pr_view = pr_json()
    env.runner.pr_reviews = review_threads([], [SUMMARY])

    session = await env.monitor.refresh(await env.store.get(session.id))

    assert len(env.sent) == 1
    (merge,) = await env.merges(session.id)
    assert merge.status is ApprovalStatus.PENDING


async def test_a_review_summary_blocks_the_merge_only_until_it_is_sent(env: Env) -> None:
    session = await opened(env, review_threads([], [SUMMARY]))
    assert await env.merges(session.id) == []

    await env.monitor.send_review(session.id)

    (merge,) = await env.merges(session.id)
    assert merge.status is ApprovalStatus.PENDING
    await env.monitor.refresh(await env.store.get(session.id))
    assert len(await env.merges(session.id)) == 1


async def test_nests_replies_on_the_users_own_review_raise_nothing_again(env: Env) -> None:
    """Seen live: the user is the only reviewer, with auto send on."""
    own = [thread(f"T{n}", (f"C{n}", "giorgos", f"Fix {n}")) for n in range(2)]
    session = await opened(env, review_threads(own, []))
    await env.monitor.set_auto_send(session.id, True)
    session = await env.monitor.refresh(await env.store.get(session.id))
    assert len(env.sent) == 1

    await env.monitor.reply_addressed(session.id, "abc1234def")
    replied = [
        thread(f"T{n}", (f"C{n}", "giorgos", f"Fix {n}"), (f"N{n}", "giorgos", NEST_REPLY))
        for n in range(2)
    ]
    env.runner.pr_reviews = review_threads(replied, [])
    session = await env.monitor.refresh(await env.store.get(session.id))
    await env.monitor.reply_addressed(session.id, "abc1234def")

    assert session.review is not None
    assert session.review.pending() == []
    assert session.review.replied == ["T0:C0", "T1:C1"]
    assert len(env.sent) == 1
    mutations = [c for c in env.runner.calls if c[4] == f"query={REPLY}"]
    assert len(mutations) == 2
    assert "giorgos: Fix 0" in session.review.items[0].body
    assert "sent by Nest" not in session.review.items[0].body


NEST_REPLY = "Addressed in abc1234 (sent by Nest)"
