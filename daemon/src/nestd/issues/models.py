"""GitHub issues as Nest reads them (B101). Nest never writes to GitHub."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from nestd.config.models import IssueShow

type IssueState = Literal["open", "closed"]


class IssueRef(BaseModel):
    """The issue a chat was started from."""

    number: int
    title: str
    url: str


class LinkedPr(BaseModel):
    number: int
    url: str


class IssueSummary(IssueRef):
    labels: list[str]
    # Comments by people; bots' are not counted.
    comments: int
    updated_at: datetime
    # Pull requests of the same repository that close the issue, in GitHub's order.
    prs: list[LinkedPr]
    # The newest open chat of the project started from the issue, read for each request.
    chat: str | None = None


class IssueList(BaseModel):
    # False when the project has no GitHub remote.
    available: bool
    show: IssueShow
    issues: list[IssueSummary]


class IssueComment(BaseModel):
    author: str
    created_at: datetime | None
    body: str


class Issue(IssueRef):
    body: str
    labels: list[str]
    state: IssueState
    author: str
    # Comments by people, oldest first.
    comments: list[IssueComment]

    def ref(self) -> IssueRef:
        return IssueRef(number=self.number, title=self.title, url=self.url)
