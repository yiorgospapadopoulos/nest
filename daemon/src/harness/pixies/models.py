"""Pixies and their files, as the API and the store see them (D072)."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from harness.config.models import Effort, PermissionMode

type Mascot = Literal[
    "invader", "ghost", "cat", "owl", "robot", "frog", "mushroom", "bunny", "crab", "sprout"
]
type Background = Literal["plain", "meadow", "dusk", "night", "dawn"]
# Which harness tools a pixie gets (stage 3); every level includes the ones before it.
type Autonomy = Literal["observe", "message", "start", "answer"]
# What a pixie may do with its projects' files: edit them like any chat, only read them,
# or neither (its workdir only).
type ProjectAccess = Literal["edit", "read", "none"]

type Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]
type Color = Annotated[str, StringConstraints(pattern=r"^#[0-9A-Fa-f]{6}$")]


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


class CreatePixie(PixieSettings):
    # Derived from the name when left out.
    slug: str | None = None
    # The first SOUL.md; a short default when empty.
    soul: Annotated[str, StringConstraints(max_length=20_000)] = ""


class UpdatePixie(BaseModel):
    """Fields left out (or null) are unchanged, except that an explicit null `model` or
    `effort` sets it back to the default; `projects` uses `all_projects` to clear.
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


class PixieOrder(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Every pixie's id, each once, in the new order.
    ids: list[str]


class Pixie(PixieSettings):
    id: str
    slug: str
    position: int
    chat_session_id: str | None
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
