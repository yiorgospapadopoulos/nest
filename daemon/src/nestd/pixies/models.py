"""Pixies and their files, as the API and the store see them (D072)."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from nestd.config.models import (
    Autonomy,
    Color,
    Effort,
    Mascot,
    MaxPerDay,
    MaxRunning,
    PermissionMode,
    PixieDefaults,
    ProjectAccess,
    Severity,
)

type Background = Literal["plain", "meadow", "dusk", "night", "dawn"]

NAME_MAX = 40
type Name = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=NAME_MAX)
]


class PixieSettings(BaseModel):
    """Everything the user sets on a pixie."""

    model_config = ConfigDict(extra="forbid")

    name: Name
    mascot: Mascot = "invader"
    color: Color = "#8B7CF6"
    background: Background = "plain"
    # None: the agent defaults' model and effort.
    model: str | None = None
    effort: Effort | None = None
    permission_mode: PermissionMode = "default"
    autonomy: Autonomy = "observe"
    project_access: ProjectAccess = "edit"
    # Repo names; None means every project.
    projects: list[str] | None = None
    # Claude Code skill names; empty means every skill.
    skills: list[str] = Field(default_factory=list[str])
    can_call: list[str] = Field(default_factory=list[str])
    # Permission rules, such as "Bash(npm test:*)": never prompt, or never available.
    allowed_tools: list[str] = Field(default_factory=list[str])
    disallowed_tools: list[str] = Field(default_factory=list[str])
    hidden: bool = False
    max_running: MaxRunning = 2
    max_per_day: MaxPerDay = 5
    # The lowest severity of its reports that reaches the phone (B42).
    report_push: Severity = "action"


class CreatePixie(PixieSettings):
    # Derived from the name when left out.
    slug: str | None = None
    # The first SOUL.md; a short default when empty.
    soul: Annotated[str, StringConstraints(max_length=20_000)] = ""

    def with_defaults(self, defaults: PixieDefaults) -> "CreatePixie":
        """The fields the client left out taken from `[pixies]` (D104)."""
        wanted = {
            name: getattr(defaults, name)
            for name in _FROM_DEFAULTS
            if name not in self.model_fields_set
        }
        return self.model_copy(update=wanted)


# The `[pixies]` keys a new pixie starts with; `projects` is applied by the client.
_FROM_DEFAULTS = (
    "model",
    "autonomy",
    "project_access",
    "max_running",
    "max_per_day",
    "report_push",
)


class UpdatePixie(BaseModel):
    """Fields left out (or null) are unchanged, except that an explicit null `model` or
    `effort` sets it back to the default and an explicit null `team_id` leaves the team;
    `projects` uses `all_projects` to clear.
    """

    model_config = ConfigDict(extra="forbid")

    name: Name | None = None
    slug: str | None = None
    mascot: Mascot | None = None
    color: Color | None = None
    background: Background | None = None
    model: str | None = None
    effort: Effort | None = None
    permission_mode: PermissionMode | None = None
    autonomy: Autonomy | None = None
    project_access: ProjectAccess | None = None
    projects: list[str] | None = None
    # True sets `projects` back to every project.
    all_projects: bool = False
    skills: list[str] | None = None
    can_call: list[str] | None = None
    allowed_tools: list[str] | None = None
    disallowed_tools: list[str] | None = None
    hidden: bool | None = None
    max_running: MaxRunning | None = None
    max_per_day: MaxPerDay | None = None
    report_push: Severity | None = None
    # A team's id to join it (B40).
    team_id: str | None = None


class PixieOrder(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Every pixie's id, each once, in the new order.
    ids: list[str]


class Pixie(PixieSettings):
    id: str
    slug: str
    position: int
    # Its team, if any (B40).
    team_id: str | None = None
    chat_session_id: str | None
    created_at: datetime
    updated_at: datetime
    # Its `action` reports the user has not read (B42); counted, not stored.
    unread_action_reports: int = 0


class CreateTeam(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name
    # Derived from the name when left out; one namespace with pixie slugs.
    handle: str | None = None


class UpdateTeam(BaseModel):
    """Fields left out (or null) are unchanged."""

    model_config = ConfigDict(extra="forbid")

    name: Name | None = None
    handle: str | None = None
    # Must be one of the team's members.
    leader_id: str | None = None


class PixieTeam(BaseModel):
    """Pixies that are called together with `@handle` (B40). Its members are the pixies
    whose `team_id` is its id; the leader is one of them, None only without members.
    """

    id: str
    name: str
    handle: str
    leader_id: str | None
    position: int
    created_at: datetime
    updated_at: datetime


class FileText(BaseModel):
    """A pixie file's text and the hash a later write must name."""

    text: str
    hash: str


class WriteFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: Annotated[str, StringConstraints(max_length=200_000)]
    # The hash the writer read; None only for a note that does not exist yet.
    hash: str | None


class SearchHit(BaseModel):
    # "MEMORY.md", "notes/<name>.md" or "archive/<YYYY-MM>.md".
    file: str
    line: str


class PixieActivity(BaseModel):
    """One thing a pixie did through its Nest tools (B41)."""

    id: int
    ts: datetime
    tool: str
    # The chat it acted on, if any.
    session_id: str | None
    summary: str
