from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from harness.config.models import Effort, PermissionMode

type SessionMode = Literal["worktree", "in_place"]


class SessionState(StrEnum):
    STARTING = "starting"  # creating the worktree and running setup
    RUNNING = "running"  # a turn is in progress
    WAITING = "waiting"  # a permission prompt is pending
    IDLE = "idle"  # the turn finished; waiting for the user
    INTERRUPTED = "interrupted"  # a turn was cut off by an interrupt or a daemon restart
    FAILED = "failed"  # setup or the agent failed
    CLOSED = "closed"


IN_FLIGHT = (SessionState.STARTING, SessionState.RUNNING, SessionState.WAITING)


class NewSession(BaseModel):
    repo: str
    title: str
    prompt: str
    mode: SessionMode
    cwd: Path | None
    model: str | None
    effort: Effort | None
    permission_mode: PermissionMode
    provider: str
    # The commit the session's work is compared with: the worktree's base, or HEAD when an
    # in-place session started.
    base_ref: str | None = None


class Session(NewSession):
    id: str
    state: SessionState
    worktree_path: Path | None
    branch: str | None
    provider_session_id: str | None
    git_violation: bool
    created_at: datetime
    updated_at: datetime
    last_error: str | None
    # Set by the daemon's git actions after the user approves the work.
    commit_sha: str | None = None
    pr_url: str | None = None
    # Tools the user allowed for the rest of the session, by tool name.
    allowed_tools: list[str] = Field(default_factory=list[str])
    pinned: bool = False
    archived_at: datetime | None = None


type Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class CreateSession(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repo: str
    prompt: Text
    # Defaults to a short title derived from the prompt.
    title: Annotated[Text, StringConstraints(max_length=200)] | None = None
    # Defaults to the repo's `worktree.default`.
    mode: SessionMode | None = None
    # Defaults come from the `agents` settings.
    model: str | None = None
    effort: Effort | None = None
    permission_mode: PermissionMode | None = None
    attachment_ids: list[str] = Field(default_factory=list[str])
    # In-place sessions refuse a checkout with uncommitted changes unless this is set.
    allow_dirty: bool = False


class SendMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: Text
    attachment_ids: list[str] = Field(default_factory=list[str])


class UpdateSession(BaseModel):
    """Fields left out (or null) are unchanged."""

    model_config = ConfigDict(extra="forbid")

    model: str | None = None
    permission_mode: PermissionMode | None = None
    title: Annotated[Text, StringConstraints(max_length=120)] | None = None
    pinned: bool | None = None
    # True archives the session and closes its agent run; false restores it.
    archived: bool | None = None
