import logging
from datetime import timedelta
from pathlib import Path

import pytest

from nestd.config.models import IssuesConfig, RepoConfig
from nestd.gitops.runner import CommandError
from nestd.issues.errors import IssueClosedError, IssueReadError, NoGitHubRemoteError
from nestd.issues.service import CACHE_TTL, IssueService
from tests.fake_runner import FakeRunner
from tests.fakes import FakeClock
from tests.github_support import REPO_URL, fixture, issue_view


class Env:
    def __init__(self, tmp_path: Path, clock: FakeClock) -> None:
        self.clock = clock
        self.runner = FakeRunner()
        self.repo = RepoConfig(name="repo", path=tmp_path, remote_url=REPO_URL)
        self.cwd = tmp_path / "neutral"
        # The chat started from each issue, as the session store finds them.
        self.chats: dict[int, str] = {}
        self.service = IssueService(
            repo=lambda _name: self.repo,
            run=self.runner,
            clock=clock,
            cwd=self.cwd,
            chats=self.chats_of,
        )

    async def chats_of(self, name: str) -> dict[int, str]:
        assert name == "repo"
        return dict(self.chats)

    def lists(self) -> list[tuple[str, ...]]:
        return [call for call in self.runner.calls if call[1:3] == ("issue", "list")]


@pytest.fixture
def env(tmp_path: Path, clock: FakeClock) -> Env:
    return Env(tmp_path, clock)


async def test_open_issues_are_listed_with_gh_outside_the_checkout(env: Env) -> None:
    env.runner.issue_list = fixture("issue_list")

    listed = await env.service.list_issues("repo")

    assert listed.available
    assert listed.show == "all"
    assert [issue.number for issue in listed.issues] == [120, 118, 117]
    assert env.lists() == [
        (
            *("gh", "issue", "list", "--repo", "me/repo", "--state", "open"),
            *("--limit", "50", "--json"),
            "number,title,labels,comments,updatedAt,url,author,closedByPullRequestsReferences",
        )
    ]


@pytest.mark.parametrize("setting", ["mine", "assigned"])
async def test_mine_lists_only_the_users_issues(env: Env, setting: str) -> None:
    # "assigned" is the setting's earlier name for "mine".
    env.repo = env.repo.model_copy(
        update={"issues": IssuesConfig.model_validate({"show": setting})}
    )
    env.runner.issue_list = "[]"

    listed = await env.service.list_issues("repo")

    assert (listed.show, listed.issues) == ("mine", [])
    assert env.lists()[0][-2:] == ("--assignee", "@me")


async def test_the_client_chooses_over_the_setting_and_each_choice_is_kept_apart(
    env: Env,
) -> None:
    env.runner.issue_list = fixture("issue_list")
    everyone = await env.service.list_issues("repo")
    env.runner.issue_list = "[]"

    mine = await env.service.list_issues("repo", show="mine")
    again = await env.service.list_issues("repo", show="all")
    mine_again = await env.service.list_issues("repo", show="mine")

    assert (everyone.show, len(everyone.issues)) == ("all", 3)
    assert (mine.show, mine.issues) == ("mine", [])
    assert again == everyone
    assert mine_again == mine
    assert [call[-2:] == ("--assignee", "@me") for call in env.lists()] == [False, True]


async def test_each_issue_names_its_chat_fresh_even_from_the_cache(env: Env) -> None:
    env.runner.issue_list = fixture("issue_list")
    first = await env.service.list_issues("repo")

    env.chats[118] = "s1"
    second = await env.service.list_issues("repo")

    assert [issue.chat for issue in first.issues] == [None, None, None]
    assert [(issue.number, issue.chat) for issue in second.issues] == [
        (120, None),
        (118, "s1"),
        (117, None),
    ]
    assert len(env.lists()) == 1


async def test_the_list_is_kept_a_minute_unless_refreshed(env: Env) -> None:
    env.runner.issue_list = fixture("issue_list")
    await env.service.list_issues("repo")

    env.runner.issue_list = "[]"
    env.clock.advance(CACHE_TTL - timedelta(seconds=1))
    assert len((await env.service.list_issues("repo")).issues) == 3
    assert len(env.lists()) == 1

    assert (await env.service.list_issues("repo", refresh=True)).issues == []
    env.runner.issue_list = fixture("issue_list")
    env.clock.advance(CACHE_TTL)
    assert len((await env.service.list_issues("repo")).issues) == 3
    assert len(env.lists()) == 3


async def test_a_changed_setting_is_not_answered_from_the_cache(env: Env) -> None:
    env.runner.issue_list = fixture("issue_list")
    await env.service.list_issues("repo")
    env.repo = env.repo.model_copy(update={"issues": IssuesConfig(show="mine")})

    assert (await env.service.list_issues("repo")).show == "mine"
    assert len(env.lists()) == 2


@pytest.mark.parametrize(
    "repo",
    [
        RepoConfig(name="repo", path=Path("/x")),
        RepoConfig(name="repo", path=Path("/x"), remote_url="git@gitlab.com:me/repo.git"),
        RepoConfig(name="repo", path=Path("/x"), git=False),
    ],
)
async def test_a_project_without_a_github_remote_has_no_issues(env: Env, repo: RepoConfig) -> None:
    env.repo = repo

    listed = await env.service.list_issues("repo")

    assert (listed.available, listed.issues) == (False, [])
    assert env.runner.calls == []
    with pytest.raises(NoGitHubRemoteError):
        await env.service.fetch(repo, 118)


async def test_a_failed_read_is_a_short_reason_never_logged(
    env: Env, caplog: pytest.LogCaptureFixture
) -> None:
    secret = "token ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
    env.runner.failures["gh issue list"] = CommandError(
        ["gh"], 1, f"some detail {secret}\nHTTP 404: Not Found (https://api.github.com/graphql)\n"
    )

    with caplog.at_level(logging.WARNING), pytest.raises(IssueReadError) as raised:
        await env.service.list_issues("repo")

    assert raised.value.status_code == 502
    assert str(raised.value) == (
        "could not read the issues of me/repo: HTTP 404: Not Found (https://api.github.com/graphql)"
    )
    assert "could not read the issues of me/repo (CommandError)" in caplog.text
    assert "404" not in caplog.text
    assert "ghp_" not in str(raised.value)


async def test_gh_missing_or_answering_nonsense_is_a_read_error(env: Env) -> None:
    env.runner.failures["gh issue list"] = FileNotFoundError("gh")
    with pytest.raises(IssueReadError, match="gh is not available"):
        await env.service.list_issues("repo")

    env.runner.issue_list = "not json"
    with pytest.raises(IssueReadError, match="gh answered something unexpected"):
        await env.service.list_issues("repo")

    env.runner.failures["gh issue view"] = CommandError(["gh"], 1, "")
    with pytest.raises(IssueReadError, match=r"#118 of me/repo: gh failed$"):
        await env.service.fetch(env.repo, 118)


async def test_one_open_issue_is_read_each_time(env: Env) -> None:
    env.runner.issue_view = fixture("issue_view")

    issue = await env.service.fetch(env.repo, 118)
    await env.service.fetch(env.repo, 118)

    assert issue.title == "Usage meter shows the wrong reset"
    views = [call for call in env.runner.calls if call[1:3] == ("issue", "view")]
    assert (
        views
        == [
            (
                *("gh", "issue", "view", "118", "--repo", "me/repo", "--json"),
                "number,title,body,labels,url,state,author,comments",
            )
        ]
        * 2
    )


async def test_a_closed_issue_is_refused(env: Env) -> None:
    env.runner.issue_view = issue_view(state="CLOSED")

    with pytest.raises(IssueClosedError, match="Issue #118 is closed"):
        await env.service.fetch(env.repo, 118)
