"""Read a pull request's review comments with the user's `gh` login (B101).

One read-only GraphQL query; the pull request goes in as variables, never into the query
text. The one write: after a push of the agent's work, a reply on each thread it was sent
(`REPLY`), with the thread and text as variables; threads are never resolved.

Resolved threads and bots' comments are left out, and the text is cleaned as it is read,
so clients and the agent only ever see the cleaned text.
"""

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field

from nestd.gitops.runner import CommandRunner
from nestd.issues.github import GhAuthor, author_name, is_bot
from nestd.prs.models import ReviewComment
from nestd.prs.untrusted import clean, one_line

QUERY = """query($owner: String!, $name: String!, $number: Int!) {
  viewer { login }
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      reviewThreads(first: 100) {
        nodes {
          id isResolved isOutdated path line originalLine
          comments(first: 50) { nodes { id author { login __typename } body url createdAt } }
        }
      }
      reviews(last: 50) { nodes { id state body author { login __typename } url submittedAt } }
    }
  }
}"""
REPLY = """mutation($thread: ID!, $body: String!) {
  addPullRequestReviewThreadReply(input: {pullRequestReviewThreadId: $thread, body: $body}) {
    comment { id }
  }
}"""
# What Nest's replies say (see `reply_addressed`); they are not review feedback.
_NEST_REPLY = re.compile(r"Addressed in [0-9a-f]{7,40} \(sent by Nest\)")
# Review states whose text is feedback; an approval's text is not.
_FEEDBACK_STATES = frozenset({"COMMENTED", "CHANGES_REQUESTED"})
# The states that say what a reviewer thinks of the pull request now.
_VERDICTS = frozenset({"APPROVED", "CHANGES_REQUESTED", "DISMISSED"})


class _Camel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class _Comment(_Camel):
    id: str
    author: GhAuthor | None = None
    body: str = ""
    url: str = ""
    created_at: datetime | None = Field(default=None, alias="createdAt")


class _Comments(_Camel):
    nodes: list[_Comment]


class _Thread(_Camel):
    id: str
    resolved: bool = Field(alias="isResolved")
    outdated: bool = Field(default=False, alias="isOutdated")
    path: str = ""
    line: int | None = None
    original_line: int | None = Field(default=None, alias="originalLine")
    comments: _Comments


class _Threads(_Camel):
    nodes: list[_Thread]


class _Review(_Camel):
    id: str
    state: str
    body: str = ""
    author: GhAuthor | None = None
    url: str = ""
    submitted_at: datetime | None = Field(default=None, alias="submittedAt")


class _Reviews(_Camel):
    nodes: list[_Review]


class _PullRequest(_Camel):
    threads: _Threads = Field(alias="reviewThreads")
    reviews: _Reviews


class _Repository(_Camel):
    pull_request: _PullRequest | None = Field(alias="pullRequest")


class _Viewer(_Camel):
    login: str


class _Data(_Camel):
    # The user gh is logged in as.
    viewer: _Viewer
    repository: _Repository | None


class _Answer(_Camel):
    data: _Data


@dataclass(frozen=True)
class ReviewRead:
    items: list[ReviewComment]
    # A reviewer's latest verdict asks for changes.
    changes_requested: bool


async def fetch_reviews(run: CommandRunner, url: str, cwd: Path) -> str:
    """The query's answer for the pull request at `url`; raises CommandError or OSError.

    Owner and name go in with `-f`, as strings gh never reads a file for (`-F` would read
    one for a value starting with `@`); only the number is typed.
    """
    owner, name, _, number = urlparse(url).path.strip("/").split("/")[:4]
    argv = [
        *("gh", "api", "graphql", "-f", f"query={QUERY}"),
        *("-f", f"owner={owner}", "-f", f"name={name}", "-F", f"number={int(number)}"),
    ]
    return await run(argv, cwd)


async def reply_to_thread(run: CommandRunner, cwd: Path, thread_id: str, body: str) -> None:
    """Post `body` as a reply on the review thread; raises CommandError or OSError."""
    argv = [
        *("gh", "api", "graphql", "-f", f"query={REPLY}"),
        *("-f", f"thread={thread_id}", "-f", f"body={body}"),
    ]
    await run(argv, cwd)


def parse_reviews(output: str) -> ReviewRead:
    answer = _Answer.model_validate_json(output)
    repository = answer.data.repository
    pr = None if repository is None else repository.pull_request
    if pr is None:
        return ReviewRead(items=[], changes_requested=False)
    viewer = answer.data.viewer.login
    items = [
        item for thread in pr.threads.nodes if (item := _thread_item(thread, viewer)) is not None
    ]
    items += [_review_item(review) for review in pr.reviews.nodes if _is_feedback(review)]
    return ReviewRead(items=items, changes_requested=_changes_requested(pr.reviews.nodes))


def _thread_item(thread: _Thread, viewer: str) -> ReviewComment | None:
    """An unresolved thread with comments by people, as one item, without the replies
    Nest posted as the user. Its id names the newest comment not by the user, so the
    user's own replies leave it as it was; in a thread of the user's own comments only (on
    their own pull request) it names the first, which no later reply changes.
    """
    comments = [
        comment
        for comment in thread.comments.nodes
        if not is_bot(comment.author) and not _nest_reply(comment, viewer)
    ]
    if thread.resolved or not comments:
        return None
    others = [c for c in comments if c.author is None or c.author.login != viewer]
    first, last = comments[0], others[-1] if others else comments[0]
    outdated = thread.outdated or thread.line is None
    return ReviewComment(
        id=f"{thread.id}:{last.id}",
        kind="thread",
        path=one_line(thread.path) or None,
        line=thread.original_line if thread.line is None else thread.line,
        outdated=outdated,
        author=one_line(author_name(first.author)),
        body="\n\n".join(
            f"{one_line(author_name(comment.author))}: {clean(comment.body).strip()}"
            for comment in comments
        ),
        url=first.url,
        created_at=first.created_at,
    )


def _nest_reply(comment: _Comment, viewer: str) -> bool:
    """A reply Nest posted with the user's login after pushing the agent's work."""
    by_viewer = comment.author is not None and comment.author.login == viewer
    return by_viewer and _NEST_REPLY.fullmatch(comment.body.strip()) is not None


def _is_feedback(review: _Review) -> bool:
    return (
        review.state in _FEEDBACK_STATES and bool(review.body.strip()) and not is_bot(review.author)
    )


def _review_item(review: _Review) -> ReviewComment:
    return ReviewComment(
        id=review.id,
        kind="review",
        author=one_line(author_name(review.author)),
        body=clean(review.body).strip(),
        url=review.url,
        created_at=review.submitted_at,
    )


def _changes_requested(reviews: list[_Review]) -> bool:
    latest: dict[str, str] = {}
    for review in reviews:
        if review.state in _VERDICTS and not is_bot(review.author):
            latest[author_name(review.author)] = review.state
    return "CHANGES_REQUESTED" in latest.values()
