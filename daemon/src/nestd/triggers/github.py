"""Read a repository's events and finished CI runs with the user's `gh` login (B148).

Each feed is asked for with the ETag of its last answer, so an unchanged one costs GitHub
nothing (a 304, which gh reports as a failure). gh runs outside any checkout and is told
the repository, so it reads nothing an agent wrote (SEC-17). Nothing is written.

GitHub's events leave most of a pull request out, so a pull request an event matches is
read on its own (`fetch_pull`).
"""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from nestd.gitops.runner import CommandError, CommandRunner
from nestd.prs.untrusted import clean, one_line
from nestd.triggers.models import GitHubEvent, GitHubEventKind

type Feed = Literal["events", "runs"]

# Characters of an event's text kept.
TEXT_CHARS = 1000
EVENTS_PAGE = 100
RUNS_PAGE = 30
_NOT_MODIFIED = "HTTP 304"
_RATE_LIMITED = ("rate limit", "HTTP 429")
CI_FAILED = frozenset({"failure", "timed_out", "startup_failure"})


class RateLimitedError(Exception):
    """GitHub asked Nest to slow down."""


@dataclass(frozen=True)
class FeedAnswer:
    # None when nothing changed since `etag`.
    body: str | None
    etag: str | None


def feed_path(repo: str, feed: Feed) -> str:
    if feed == "events":
        return f"repos/{repo}/events?per_page={EVENTS_PAGE}"
    return f"repos/{repo}/actions/runs?per_page={RUNS_PAGE}&status=completed"


async def fetch_feed(
    run: CommandRunner, cwd: Path, repo: str, feed: Feed, etag: str | None
) -> FeedAnswer:
    """Raises RateLimitedError, CommandError or OSError."""
    argv = ["gh", "api", "--include"]
    if etag is not None:
        argv += ["--header", f"If-None-Match: {etag}"]
    argv.append(feed_path(repo, feed))
    try:
        output = await run(argv, cwd)
    except CommandError as error:
        if _NOT_MODIFIED in error.stderr:
            return FeedAnswer(body=None, etag=etag)
        if any(sign in error.stderr for sign in _RATE_LIMITED):
            raise RateLimitedError from None
        raise
    head, _, body = output.replace("\r\n", "\n").partition("\n\n")
    return FeedAnswer(body=body, etag=_header(head, "etag"))


async def fetch_pull(run: CommandRunner, cwd: Path, repo: str, number: int) -> str:
    """gh's output for one pull request; raises CommandError or OSError."""
    return await run(["gh", "api", f"repos/{repo}/pulls/{number}"], cwd)


def _header(head: str, name: str) -> str | None:
    for line in head.split("\n")[1:]:
        key, _, value = line.partition(":")
        if key.strip().lower() == name:
            return value.strip() or None
    return None


# GitHub's shapes, as much of them as Nest reads.


class _Loose(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class _User(_Loose):
    login: str = ""
    type: str = ""


class _Label(_Loose):
    name: str


class _Ref(_Loose):
    ref: str = ""


class _Issue(_Loose):
    number: int
    title: str = ""
    html_url: str = ""
    body: str | None = None
    labels: list[_Label] = Field(default_factory=list[_Label])
    # Present on a pull request.
    pull_request: dict[str, object] | None = None


class _Pull(_Loose):
    number: int
    title: str = ""
    html_url: str = ""
    labels: list[_Label] | None = None
    base: _Ref | None = None


class _Comment(_Loose):
    body: str | None = None
    html_url: str = ""


class _Review(_Loose):
    body: str | None = None
    html_url: str = ""
    state: str = ""


class _Payload(_Loose):
    action: str | None = None
    issue: _Issue | None = None
    pull_request: _Pull | None = None
    comment: _Comment | None = None
    review: _Review | None = None


class _Event(_Loose):
    id: str
    type: str
    actor: _User = Field(default_factory=_User)
    payload: _Payload
    created_at: datetime


class _RepoName(_Loose):
    full_name: str = ""


class _Run(_Loose):
    id: int
    run_attempt: int = 1
    name: str = ""
    display_title: str = ""
    html_url: str = ""
    head_branch: str | None = None
    # The fork a pull request's run came from, or the repository itself.
    head_repository: _RepoName | None = None
    conclusion: str | None = None
    actor: _User = Field(default_factory=_User)
    updated_at: datetime


class _Runs(_Loose):
    workflow_runs: list[_Run]


_EVENTS = TypeAdapter(list[_Event])


def parse_events(body: str, repo: str) -> list[GitHubEvent]:
    """The events Nest starts runs for, oldest first; others are left out."""
    found: list[GitHubEvent] = []
    for event in _EVENTS.validate_json(body):
        made = _from_event(event, repo)
        if made is not None:
            found.append(made)
    return sorted(found, key=lambda e: e.at)


def parse_runs(body: str, repo: str) -> list[GitHubEvent]:
    """Finished CI runs that failed or passed, oldest first."""
    found: list[GitHubEvent] = []
    for run in _Runs.model_validate_json(body).workflow_runs:
        kind: GitHubEventKind | None = (
            "ci_failed"
            if run.conclusion in CI_FAILED
            else "ci_passed"
            if run.conclusion == "success"
            else None
        )
        if kind is None:
            continue
        title = one_line(f"{run.name}: {run.display_title}" if run.display_title else run.name)
        found.append(
            GitHubEvent(
                key=f"run:{run.id}:{run.run_attempt}",
                kind=kind,
                repo=repo,
                number=None,
                title=title,
                url=run.html_url,
                author=run.actor.login,
                bot=_bot(run.actor),
                labels=None,
                branch=_run_branch(run, repo),
                text="",
                at=run.updated_at,
            )
        )
    return sorted(found, key=lambda e: e.at)


def _run_branch(run: _Run, repo: str) -> str | None:
    """A fork's branch named with its owner, `owner:main`, so it cannot pass for one of
    the repository's own branches.
    """
    head = run.head_repository
    if run.head_branch is None or head is None or head.full_name.lower() in ("", repo.lower()):
        return run.head_branch
    return f"{head.full_name.split('/')[0]}:{run.head_branch}"


def with_pull(event: GitHubEvent, body: str) -> GitHubEvent:
    """The event with its pull request's title, link, labels and target branch."""
    try:
        pull = _Pull.model_validate_json(body)
    except ValidationError:
        return event
    return event.model_copy(
        update={
            "title": one_line(pull.title) or event.title,
            "url": event.url or pull.html_url,
            "labels": [label.name for label in pull.labels or []],
            "branch": pull.base.ref if pull.base is not None else event.branch,
        }
    )


@dataclass(frozen=True)
class _Source:
    """What every event from one entry of the feed shares."""

    event: _Event
    repo: str

    def made(
        self,
        kind: GitHubEventKind,
        number: int,
        title: str,
        url: str,
        labels: list[str] | None,
        branch: str | None,
        text: str,
        *,
        on_pull: bool = False,
    ) -> GitHubEvent:
        return GitHubEvent(
            key=f"event:{self.event.id}",
            kind=kind,
            repo=self.repo,
            number=number,
            title=title,
            url=url,
            author=self.event.actor.login,
            bot=_bot(self.event.actor),
            labels=labels,
            branch=branch,
            text=text,
            at=self.event.created_at,
            on_pull=on_pull,
        )

    def on_pull(self, kind: GitHubEventKind, pull: _Pull, url: str, text: str) -> GitHubEvent:
        return self.made(
            kind,
            pull.number,
            one_line(pull.title) or f"Pull request #{pull.number}",
            url or pull.html_url or f"https://github.com/{self.repo}/pull/{pull.number}",
            None if pull.labels is None else [label.name for label in pull.labels],
            None if pull.base is None else pull.base.ref or None,
            text,
            on_pull=True,
        )


def _from_event(event: _Event, repo: str) -> GitHubEvent | None:
    payload = event.payload
    source = _Source(event, repo)
    match event.type, payload.action:
        case "IssuesEvent", "opened" if payload.issue is not None:
            issue = payload.issue
            return source.made(
                "issue_opened",
                issue.number,
                one_line(issue.title),
                issue.html_url,
                [label.name for label in issue.labels],
                None,
                _text(issue.body),
            )
        case "PullRequestEvent", "opened" if payload.pull_request is not None:
            return source.on_pull("pr_opened", payload.pull_request, "", "")
        case "IssueCommentEvent", "created" if payload.issue is not None:
            issue, comment = payload.issue, payload.comment
            on_pull = issue.pull_request is not None
            return source.made(
                "comment",
                issue.number,
                one_line(issue.title),
                comment.html_url if comment is not None else issue.html_url,
                # A pull request's labels and branch come with it.
                None if on_pull else [label.name for label in issue.labels],
                None,
                _text(None if comment is None else comment.body),
                on_pull=on_pull,
            )
        case "PullRequestReviewCommentEvent", "created" if payload.pull_request is not None:
            comment = payload.comment
            return source.on_pull(
                "comment",
                payload.pull_request,
                "" if comment is None else comment.html_url,
                _text(None if comment is None else comment.body),
            )
        case "PullRequestReviewEvent", _ if payload.pull_request is not None:
            review = payload.review
            if review is None:
                return None
            state = review.state.lower().replace("_", " ")
            body = _text(review.body)
            return source.on_pull(
                "review",
                payload.pull_request,
                review.html_url,
                f"{state}: {body}" if body else state,
            )
        case _:
            return None


def _bot(user: _User) -> bool:
    return user.type == "Bot" or user.login.endswith("[bot]")


def _text(body: str | None) -> str:
    return clean(body or "").strip()[:TEXT_CHARS]
