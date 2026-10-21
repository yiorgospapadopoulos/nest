from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from nestd.issues.github import GhAuthor, is_bot, parse_issue, parse_issue_list
from tests.github_support import fixture, issue_view


def test_the_list_is_newest_updated_first_with_labels_and_human_comments() -> None:
    issues = parse_issue_list(fixture("issue_list"), "me/repo")

    assert [issue.number for issue in issues] == [120, 118, 117]
    usage = issues[1]
    assert usage.model_dump() == {
        "number": 118,
        "title": "Usage meter shows the wrong reset",
        "url": "https://github.com/me/repo/issues/118",
        "labels": ["bug", "ui"],
        # The stale bot's comment does not count.
        "comments": 1,
        "updated_at": datetime(2026, 10, 19, 9, 0, tzinfo=UTC),
        # Pull requests of this repository only, in GitHub's order; a fork's is dropped.
        "prs": [
            {"number": 131, "url": "https://github.com/me/repo/pull/131"},
            {"number": 129, "url": "https://github.com/Me/Repo/pull/129"},
        ],
        # Filled in per request from the chats, never from gh.
        "chat": None,
    }
    assert (issues[0].comments, issues[2].comments, issues[2].labels) == (1, 0, [])


def test_one_issue_keeps_its_body_and_only_human_comments() -> None:
    issue = parse_issue(fixture("issue_view"))

    assert (issue.number, issue.state, issue.author) == (118, "open", "giorgos")
    assert issue.labels == ["bug", "ui"]
    assert issue.body.startswith("The meter says it resets at 14:00")
    assert [(c.author, c.created_at) for c in issue.comments] == [
        ("sam", datetime(2026, 10, 19, 8, 1, 12, tzinfo=UTC))
    ]
    assert issue.ref().model_dump() == {
        "number": 118,
        "title": "Usage meter shows the wrong reset",
        "url": "https://github.com/me/repo/issues/118",
    }


def test_a_closed_issue_and_one_without_body_or_author() -> None:
    issue = parse_issue(issue_view(state="CLOSED", body=None, author=None, comments=[]))

    assert (issue.state, issue.body, issue.author, issue.comments) == ("closed", "", "ghost", [])


def test_output_that_is_not_an_issue_is_refused() -> None:
    with pytest.raises(ValidationError):
        parse_issue('{"title": "no number"}')
    with pytest.raises(ValidationError):
        parse_issue_list("Creating pull request", "me/repo")


@pytest.mark.parametrize(
    ("author", "bot"),
    [
        ({"login": "sam"}, False),
        ({"login": "github-actions[bot]"}, True),
        ({"login": "renovate", "is_bot": True}, True),
        ({"login": "coderabbitai", "__typename": "Bot"}, True),
        ({"login": "sam", "__typename": "User"}, False),
        (None, False),
    ],
)
def test_bots_are_told_by_type_flag_or_login(author: dict[str, object] | None, bot: bool) -> None:
    assert is_bot(None if author is None else GhAuthor.model_validate(author)) is bot
