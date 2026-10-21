"""Read a repository's issues with the user's `gh` login (B101); nothing is written.

gh runs outside any checkout and is told the repository, so it reads nothing an agent
wrote (SEC-17).
"""

from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from nestd.gitops.runner import CommandRunner
from nestd.issues.models import Issue, IssueComment, IssueSummary, LinkedPr

LIST_LIMIT = 50
LIST_FIELDS = "number,title,labels,comments,updatedAt,url,author,closedByPullRequestsReferences"
VIEW_FIELDS = "number,title,body,labels,url,state,author,comments"
# Who wrote a comment GitHub no longer knows, as GitHub itself shows it.
GHOST = "ghost"


class GhAuthor(BaseModel):
    """An author as gh or GitHub's GraphQL API reports one."""

    model_config = ConfigDict(populate_by_name=True)

    login: str = ""
    typename: str = Field(default="", alias="__typename")
    is_bot: bool = False


class _GhLabel(BaseModel):
    name: str


class _GhComment(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    author: GhAuthor | None = None
    body: str = ""
    created_at: datetime | None = Field(default=None, alias="createdAt")


class _GhIssue(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    number: int
    title: str
    url: str
    labels: list[_GhLabel] = Field(default_factory=list[_GhLabel])
    comments: list[_GhComment] = Field(default_factory=list[_GhComment])
    author: GhAuthor | None = None

    def human_comments(self) -> list[_GhComment]:
        return [comment for comment in self.comments if not is_bot(comment.author)]


class _GhOwner(BaseModel):
    login: str


class _GhRepository(BaseModel):
    name: str
    owner: _GhOwner


class _GhClosingPr(BaseModel):
    number: int
    url: str
    repository: _GhRepository


class _GhListed(_GhIssue):
    updated_at: datetime = Field(alias="updatedAt")
    closing_prs: list[_GhClosingPr] = Field(
        default_factory=list[_GhClosingPr], alias="closedByPullRequestsReferences"
    )


class _GhViewed(_GhIssue):
    body: str | None = None
    state: str


_LIST = TypeAdapter(list[_GhListed])


def is_bot(author: GhAuthor | None) -> bool:
    """A GitHub App or another bot account; a deleted account is not one."""
    if author is None:
        return False
    return author.is_bot or author.typename == "Bot" or author.login.endswith("[bot]")


def author_name(author: GhAuthor | None) -> str:
    return GHOST if author is None or not author.login else author.login


async def list_issues(run: CommandRunner, cwd: Path, repo: str, mine: bool) -> str:
    """gh's output for the repository's open issues; raises CommandError or OSError."""
    argv = [
        *("gh", "issue", "list", "--repo", repo, "--state", "open"),
        *("--limit", str(LIST_LIMIT), "--json", LIST_FIELDS),
    ]
    if mine:
        argv += ["--assignee", "@me"]
    return await run(argv, cwd)


async def view_issue(run: CommandRunner, cwd: Path, repo: str, number: int) -> str:
    """gh's output for one issue; raises CommandError or OSError."""
    argv = ["gh", "issue", "view", str(number), "--repo", repo, "--json", VIEW_FIELDS]
    return await run(argv, cwd)


def parse_issue_list(output: str, repo: str) -> list[IssueSummary]:
    """Newest updated first. gh lists issues only, never pull requests. Of the pull
    requests closing each, only those of `repo` (`owner/name`) are kept.
    """
    issues = [
        IssueSummary(
            number=issue.number,
            title=issue.title,
            url=issue.url,
            labels=[label.name for label in issue.labels],
            comments=len(issue.human_comments()),
            updated_at=issue.updated_at,
            prs=[
                LinkedPr(number=pr.number, url=pr.url)
                for pr in issue.closing_prs
                if f"{pr.repository.owner.login}/{pr.repository.name}".lower() == repo.lower()
            ],
        )
        for issue in _LIST.validate_json(output)
    ]
    return sorted(issues, key=lambda issue: issue.updated_at, reverse=True)


def parse_issue(output: str) -> Issue:
    issue = _GhViewed.model_validate_json(output)
    return Issue(
        number=issue.number,
        title=issue.title,
        url=issue.url,
        body=issue.body or "",
        labels=[label.name for label in issue.labels],
        state="open" if issue.state == "OPEN" else "closed",
        author=author_name(issue.author),
        comments=[
            IssueComment(
                author=author_name(comment.author),
                created_at=comment.created_at,
                body=comment.body,
            )
            for comment in issue.human_comments()
        ],
    )
