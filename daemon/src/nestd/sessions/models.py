from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StringConstraints

from nestd.config.models import Effort, ModelChoice, PermissionMode, SessionMode
from nestd.providers.base import ContextUsage, LimitWindow, RewindResult
from nestd.prs.models import PrStatus
from nestd.stuck.models import StuckFlag

# A pixie's chat has no project; its `repo` names the pixie instead (D072).
PIXIE_REPO_PREFIX = "pixie:"


def pixie_repo(pixie_id: str) -> str:
    return f"{PIXIE_REPO_PREFIX}{pixie_id}"


# A user message the daemon sends: to a pixie, the outcome of chats it started (B41) or a
# report one of its habit runs made (B42); to a chat going on after the usage limit reset
# with nothing queued, the message that lets Claude continue (`limit_resume`, B78).
type MessageOrigin = Literal["report_back", "report", "limit_resume"]


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


class LimitPause(BaseModel):
    """A chat paused at the subscription's usage limit (B78): messages wait in its queue
    until `resume_at`, when the daemon goes on with them.
    """

    # The window whose limit was reached; None when the engine did not say.
    window: LimitWindow | None
    # When the engine said the limit resets; None when it did not say.
    resets_at: datetime | None
    # When the daemon goes on: a margin after the reset, or a fixed delay when unknown.
    resume_at: datetime
    since: datetime


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
    # The engine the chat runs on, such as "claude" or "codex" (B91).
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
    # Set for a pixie called from the chat `called_by` (B91): it has the called pixie's
    # `pixie_id`, runs in the caller's folder and ends with its first turn, its report.
    called_by: str | None = None


class Session(NewSession):
    id: str
    state: SessionState
    worktree_path: Path | None
    branch: str | None
    provider_session_id: str | None
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
    # Set while the chat is paused at the usage limit (B78).
    limit_pause: LimitPause | None = None
    # A rewound or forked conversation its next run cuts into a new engine session: resume
    # `fork_from` up to the entry `fork_at`, refusing unless only the turn of `fork_drops`
    # goes when that is set (B59). Cleared once the run reports the new session.
    fork_from: str | None = Field(default=None, exclude=True)
    fork_at: str | None = Field(default=None, exclude=True)
    fork_drops: str | None = Field(default=None, exclude=True)


type Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class CreateSession(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repo: str
    prompt: Text
    # Defaults to a short title derived from the prompt.
    title: Annotated[Text, StringConstraints(max_length=200)] | None = None
    # Defaults to the repo's `worktree.default` when set, else `[agents] default_mode`.
    mode: SessionMode | None = None
    # Defaults come from the `agents` settings when the chat is on their engine, else the
    # engine's default model, Medium (or the closest level) and Ask (B94).
    model: ModelChoice = None
    effort: Effort | None = None
    permission_mode: PermissionMode | None = None
    # The engine the chat runs on, such as "claude" or "codex" (B91); null is the agent
    # defaults' engine (B94).
    provider: Text | None = None
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


# What a rewind restores to before a user message, as in Claude Code: the files the agent
# changed (IMP-02), the conversation (B59), or both.
type Restore = Literal["code", "conversation", "both"]


class RewindRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # The id of the `session.user_message` event to restore to before (IMP-02).
    message: int = Field(ge=1)
    restore: Restore = "code"


class ForkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # The id of the `session.user_message` event the new chat's conversation stops before.
    message: int = Field(ge=1)


class AttachmentSummary(BaseModel):
    id: str
    filename: str
    media_type: str
    size: int


class RewindReply(RewindResult):
    """A rewind previewed or done (B59). The file fields are the files' part; with only
    the conversation restored they stay empty, `can_rewind` true.
    """

    restore: Restore = "code"
    # The rewound message, for the composer when the conversation is restored ("edit").
    text: str | None = None
    attachments: list[AttachmentSummary] = Field(default_factory=list[AttachmentSummary])


class QueuedMessage(BaseModel):
    """A message sent while a turn ran, waiting until the agent reads it (D032, B59)."""

    id: str
    text: str
    attachments: list[AttachmentSummary]
    created_at: datetime
    # Written into the running turn: the agent reads it at its next step, or starts its
    # next turn with it. Otherwise it waits for the turn to end (B59).
    sent: bool = False
    # Kept for the message's event when it starts; not part of the queue's payload (B41).
    from_pixie: str | None = Field(default=None, exclude=True)
    origin: MessageOrigin | None = Field(default=None, exclude=True)

    @property
    def sender(self) -> Sender:
        return Sender(self.from_pixie, self.origin)


class ForkReply(BaseModel):
    """A new chat forked from a message (B59), and that message for its composer."""

    session: Session
    text: str
    attachments: list[AttachmentSummary]


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
