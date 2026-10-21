from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from nestd.prs.models import ReviewComment
from nestd.prs.reviews import QUERY, fetch_reviews, parse_reviews
from tests.fake_runner import PR_URL, FakeRunner
from tests.github_support import fixture, review_threads, thread


def test_unresolved_threads_and_review_texts_by_people_become_items() -> None:
    read = parse_reviews(fixture("pr_review_threads"))

    assert read.items == [
        ReviewComment(
            # The user's own reply at the end does not count for the id.
            id="PRRT_kwDOK1a2b85Aaaa1:PRRC_kwDOK1a2b86Bbbb1",
            kind="thread",
            path="src/usage/meter.py",
            line=42,
            outdated=False,
            author="sam",
            body="sam: This should use the window's own reset time.\n\n"
            "giorgos: And round it to the minute.",
            url="https://github.com/me/repo/pull/7#discussion_r1800000001",
            created_at=datetime(2026, 10, 20, 11, 0, tzinfo=UTC),
        ),
        # Outdated: the line it was on, by an account GitHub no longer knows, cleaned.
        ReviewComment(
            id="PRRT_kwDOK1a2b85Aaaa3:PRRC_kwDOK1a2b86Bbbb5",
            kind="thread",
            path="src/usage/old.py",
            line=7,
            outdated=True,
            author="ghost",
            body="ghost: Drop this file.",
            url="https://github.com/me/repo/pull/7#discussion_r1800000005",
            created_at=datetime(2026, 10, 20, 11, 20, tzinfo=UTC),
        ),
        ReviewComment(
            id="PRR_kwDOK1a2b86Cccc1",
            kind="review",
            author="sam",
            body="Please fix the reset first.",
            url="https://github.com/me/repo/pull/7#pullrequestreview-2300000001",
            created_at=datetime(2026, 10, 20, 11, 1, tzinfo=UTC),
        ),
    ]
    # sam's latest review requested changes.
    assert read.changes_requested


def test_a_later_approval_by_the_same_reviewer_takes_changes_requested_back() -> None:
    reviews = [
        {
            "id": "PRR_1",
            "state": "CHANGES_REQUESTED",
            "body": "",
            "author": {"login": "sam", "__typename": "User"},
            "url": "https://github.com/me/repo/pull/7#pullrequestreview-1",
            "submittedAt": "2026-10-20T11:00:00Z",
        },
        {
            "id": "PRR_2",
            "state": "COMMENTED",
            "body": "One more thing.",
            "author": {"login": "sam", "__typename": "User"},
            "url": "https://github.com/me/repo/pull/7#pullrequestreview-2",
            "submittedAt": "2026-10-20T11:10:00Z",
        },
        {
            "id": "PRR_3",
            "state": "APPROVED",
            "body": "",
            "author": {"login": "sam", "__typename": "User"},
            "url": "https://github.com/me/repo/pull/7#pullrequestreview-3",
            "submittedAt": "2026-10-20T11:20:00Z",
        },
    ]

    read = parse_reviews(review_threads([], reviews))

    assert not read.changes_requested
    assert [item.id for item in read.items] == ["PRR_2"]


def test_a_new_reply_gives_a_thread_a_new_id() -> None:
    before = parse_reviews(review_threads([thread("T1", ("C1", "sam", "Fix"))], []))
    after = parse_reviews(
        review_threads([thread("T1", ("C1", "sam", "Fix"), ("C2", "sam", "Please"))], [])
    )

    assert [item.id for item in before.items] == ["T1:C1"]
    assert [item.id for item in after.items] == ["T1:C2"]


def ids(*comments: tuple[str, str, str]) -> list[str]:
    read = parse_reviews(review_threads([thread("T1", *comments)], []))
    return [item.id for item in read.items]


ASKED = ("C1", "sam", "Fix")
NEST = ("C2", "giorgos", "Addressed in abc1234 (sent by Nest)")


def test_replies_by_the_user_or_nest_keep_a_thread_as_it_was() -> None:
    mine = ("C3", "giorgos", "Done, see the new name")

    assert ids(ASKED) == ["T1:C1"]
    assert ids(ASKED, NEST) == ["T1:C1"]
    assert ids(ASKED, mine) == ["T1:C1"]
    # Someone else's reply raises it again.
    assert ids(ASKED, NEST, ("C4", "sam", "Not quite")) == ["T1:C4"]


def test_a_thread_of_the_users_own_keeps_its_first_comments_id() -> None:
    """As when the user reviews their own pull request (seen live)."""
    own = ("C5", "giorgos", "Rename this")

    assert ids(own) == ["T1:C5"]
    assert ids(own, NEST) == ["T1:C5"]
    assert ids(own, ("C6", "giorgos", "And the test too")) == ["T1:C5"]
    assert ids(own, NEST, ("C7", "giorgos", "Better now"), NEST) == ["T1:C5"]


def test_nests_own_replies_are_left_out_of_the_text() -> None:
    other = ("C8", "sam", "Addressed in abc1234 (sent by Nest)")

    (item,) = parse_reviews(review_threads([thread("T1", ASKED, NEST, other)], [])).items

    # Only the user's Nest replies are Nest's; the same words by someone else count.
    assert (item.id, item.body) == ("T1:C8", "sam: Fix\n\nsam: Addressed in abc1234 (sent by Nest)")
    assert ids(NEST) == []


def test_a_pull_request_github_does_not_find_has_no_review_comments() -> None:
    read = parse_reviews('{"data": {"viewer": {"login": "me"}, "repository": null}}')

    assert (read.items, read.changes_requested) == ([], False)


def test_output_that_is_not_an_answer_is_refused() -> None:
    with pytest.raises(ValidationError):
        parse_reviews('{"errors": [{"message": "Something went wrong"}]}')


async def test_the_query_takes_the_pull_request_as_variables(tmp_path: Path) -> None:
    runner = FakeRunner()

    await fetch_reviews(runner, PR_URL, tmp_path)

    assert runner.calls == [
        (
            *("gh", "api", "graphql", "-f", f"query={QUERY}"),
            *("-f", "owner=me", "-f", "name=repo", "-F", "number=7"),
        )
    ]
    assert "mutation" not in QUERY
    assert "viewer { login }" in QUERY
