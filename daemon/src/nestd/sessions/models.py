from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StringConstraints

from nestd.config.models import Effort, PermissionMode, SessionMode
from nestd.providers.base import ContextUsage
from nestd.prs.models import PrStatus
from nestd.stuck.models import StuckFlag

# A pixie's chat has no project; its `repo` names the pixie instead (D072).
PIXIE_REPO_PREFIX = "pixie:"


def pixie_repo(pixie_id: str) -> str:
    return f"{PIXIE_REPO_PREFIX}{pixie_id}"


# A user message the daemon sends a pixie: the outcome of chats it started (B41), or a
# report one of its habit runs made (B42).
type MessageOrigin = Literal["report_back", "report"]


@dataclass(frozen=True)
class Sender:
    """Who a user message comes from besides the user: the pixie that sent it into the
    chat, or the daemon's report to a pixie (B41). Both None: the user.
    """

    from_pixie: str | None = None
    origin: MessageOrigin | None = None

    def payload(self) -> dict[str, JsonValue]:
        return {"from_pixie": self.from_pixie, "origin": self.origin}


USER = Sender()


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
    # True while the mode is Claude Code's own (its `defaultMode`) and the engine has not
    # reported it yet: `permission_mode` holds "default" until then and runs open without
    # a mode (IMP-06).
    follows_claude_code_mode: bool = False
    provider: str
    # The commit the session's work is compared with: the worktree's base, or HEAD when an
    # in-place session started.
    base_ref: str | None = None
    # Set for a pixie's chat (D072); such sessions are not listed with a project's chats.
    pixie_id: str | None = None
    # The pixie that started this chat with its tools, and the batch of chats it started
    # in that turn until their report went back to it (B41).
    started_by_pixie: str | None = None
    pixie_batch: str | None = None
    # Set for a habit run's session (B42): it has the pixie's `pixie_id` but is not its chat.
    habit_run_id: str | None = None


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
    # How full the agent's context window was after its last turn (D032).
    context: ContextUsage | None = None
    # The pull request's last known status on GitHub, and a short summary of it (D034).
    pr: PrStatus | None = None
    pr_summary: str | None = None
    # Why the session looks stuck right now, if it does (D036).
    stuck: StuckFlag | None = None


type Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class CreateSession(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repo: str
    prompt: Text
    # Defaults to a short title derived from the prompt.
    title: Annotated[Text, StringConstraints(max_length=200)] | None = None
    # Defaults to the repo's `worktree.default` when set, else `[agents] default_mode`.
    mode: SessionMode | None = None
    # Defaults come from the `agents` settings.
    model: str | None = None
    effort: Effort | None = None
    permission_mode: PermissionMode | None = None
    attachment_ids: list[str] = Field(default_factory=list[str])
    # Only for a worktree chat (B55): its new branch's name instead of a generated one, and
    # the local branch it starts from instead of the default branch.
    branch: str | None = None
    base: str | None = None


class SendMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: Text
    attachment_ids: list[str] = Field(default_factory=list[str])
    # While a turn runs: stop it and start this message right after, ahead of the queue
    # (a nudge to a stuck agent, D036). Ignored when the session is idle.
    interrupt: bool = False


class RewindRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # The id of the `session.user_message` event to restore files to before (IMP-02).
    message: int = Field(ge=1)


class AttachmentSummary(BaseModel):
    id: str
    filename: str
    media_type: str
    size: int


class QueuedMessage(BaseModel):
    """A message sent while a turn ran, waiting to start the next one (D032)."""

    id: str
    text: str
    attachments: list[AttachmentSummary]
    created_at: datetime
    # Kept for the message's event when it starts; not part of the queue's payload (B41).
    from_pixie: str | None = Field(default=None, exclude=True)
    origin: MessageOrigin | None = Field(default=None, exclude=True)

    @property
    def sender(self) -> Sender:
        return Sender(self.from_pixie, self.origin)


class SendResult(Session):
    """The session a message went to; `queued_message` is set when it waits for the turn."""

    queued_message: QueuedMessage | None = None


class UpdateSession(BaseModel):
    """Fields left out (or null) are unchanged."""

    model_config = ConfigDict(extra="forbid")

    model: str | None = None
    permission_mode: PermissionMode | None = None
    # Applies when the agent run next opens: the next message reopens an idle run (I-006).
    effort: Effort | None = None
    title: Annotated[Text, StringConstraints(max_length=120)] | None = None
    pinned: bool | None = None
    # True archives the session and closes its agent run; false restores it.
    archived: bool | None = None


@dataclass(frozen=True)
class ChatImport:
    """A Claude Code chat to continue as a Nest session (D028)."""

    repo: str
    title: str
    prompt: str
    cwd: Path
    provider_session_id: str
    # Its messages as session events (type and payload), oldest first.
    history: list[tuple[str, dict[str, JsonValue]]]
