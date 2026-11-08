"""GitHub event triggers (B148, D177): which events a habit or a project's chat trigger
waits for, with its filters, and an event as Nest reads it from GitHub.

A filter applies only to events that have what it filters on: labels to issues and pull
requests (and the comments and reviews on them), branches to CI runs and the branch a pull
request goes into.
"""

from datetime import datetime
from typing import Annotated, Literal, Self, get_args

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

type GitHubEventKind = Literal[
    "issue_opened", "pr_opened", "comment", "review", "ci_failed", "ci_passed"
]
GITHUB_EVENTS: tuple[GitHubEventKind, ...] = get_args(GitHubEventKind.__value__)
# Whose events count: anyone but bots, also not the user's own, or every one.
type Authors = Literal["humans", "others", "everyone"]

NAME_MAX = 120
PROMPT_MAX = 4000
MAX_FILTERS = 20

type Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]
# A branch name or an fnmatch pattern such as `release/*`.
type Branch = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
type ProjectName = Annotated[str, StringConstraints(min_length=1, max_length=200)]
type TriggerName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=NAME_MAX)
]
type TriggerPrompt = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=PROMPT_MAX)
]
type TriggerId = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{32}$")]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EventFilter(_Strict):
    events: Annotated[list[GitHubEventKind], Field(min_length=1)]
    # Any one of them; compared without case.
    labels: Annotated[list[Label], Field(max_length=MAX_FILTERS)] = Field(
        default_factory=list[Label]
    )
    branches: Annotated[list[Branch], Field(max_length=MAX_FILTERS)] = Field(
        default_factory=list[Branch]
    )
    authors: Authors = "humans"

    @model_validator(mode="after")
    def _unique(self) -> Self:
        self.events = list(dict.fromkeys(self.events))
        self.labels = list(dict.fromkeys(self.labels))
        self.branches = list(dict.fromkeys(self.branches))
        return self


class GitHubWatch(EventFilter):
    """A habit's GitHub trigger; no projects is every project on GitHub."""

    projects: Annotated[list[ProjectName], Field(max_length=MAX_FILTERS)] = Field(
        default_factory=list[ProjectName]
    )

    @model_validator(mode="after")
    def _unique_projects(self) -> Self:
        self.projects = list(dict.fromkeys(self.projects))
        return self


class NewChatTrigger(EventFilter):
    """A project's trigger as a client creates it: the chat it starts is told `prompt`."""

    name: TriggerName
    prompt: TriggerPrompt
    enabled: bool = True


class ChatTrigger(NewChatTrigger):
    """`[[triggers]]` in a project's config: each event it matches starts a chat in the
    project, in its own worktree.
    """

    id: TriggerId


class UpdateChatTrigger(_Strict):
    """Fields left out are unchanged."""

    name: TriggerName | None = None
    prompt: TriggerPrompt | None = None
    enabled: bool | None = None
    events: Annotated[list[GitHubEventKind], Field(min_length=1)] | None = None
    labels: Annotated[list[Label], Field(max_length=MAX_FILTERS)] | None = None
    branches: Annotated[list[Branch], Field(max_length=MAX_FILTERS)] | None = None
    authors: Authors | None = None


class GitHubEvent(BaseModel):
    """An event in a repository on GitHub; everything but `key`, `kind` and `repo` was
    written on GitHub and is untrusted.
    """

    # Unique per repository and event, for dedupe.
    key: str
    kind: GitHubEventKind
    # `owner/name`.
    repo: str
    # The issue or pull request; None for a CI run.
    number: int | None
    title: str
    url: str
    author: str
    bot: bool
    # None where labels do not apply (a CI run), or are not known yet (a pull request
    # before Nest reads it).
    labels: list[str] | None
    # A CI run's branch or the branch a pull request goes into; None for issues.
    branch: str | None
    # A comment's or review's text, an issue's description, cut short.
    text: str
    at: datetime
    # Whether it is about a pull request, whose title and labels Nest reads separately.
    on_pull: bool = False


type FireOutcome = Literal["started", "queued", "skipped", "failed"]


class TriggerActivity(BaseModel):
    """What a project's chat trigger did last."""

    trigger_id: str
    outcome: FireOutcome
    reason: str | None
    at: datetime
    # The event, as GitHub named it.
    title: str
    url: str
    # The chat it started.
    session_id: str | None


class TriggerRef(BaseModel):
    """The project trigger a chat was started by, and the event."""

    id: str
    name: str
    event_title: str
    event_url: str
