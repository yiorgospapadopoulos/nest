"""Typed models for the TOML files in the user config directory."""

from pathlib import Path, PurePosixPath
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

Effort = Literal["low", "medium", "high", "xhigh", "max"]
PermissionMode = Literal["default", "acceptEdits", "bypassPermissions", "plan"]
type SessionMode = Literal["worktree", "in_place"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ServerSettings(_Strict):
    # The host is always 127.0.0.1 (D014), so only the port is configurable.
    port: int = Field(default=8765, ge=1, le=65535)
    # Browser origins allowed to open the event socket besides the daemon's own host,
    # such as "https://mac.tailnet.ts.net".
    allowed_origins: list[str] = Field(default_factory=list[str])


class AgentDefaults(_Strict):
    model: str | None = None
    effort: Effort | None = None
    permission_mode: PermissionMode = "default"
    # Where new chats work; a repo's `[worktree] default` overrides it when set (D038).
    default_mode: SessionMode = "in_place"
    # Idle agent processes are closed after this long and resumed on the next message.
    idle_close_minutes: int = Field(default=10, ge=1)


class AgentChoices(_Strict):
    """The agent defaults clients edit: `GET/PUT /api/agents/defaults` (D038)."""

    # A value of the engine's model list ("default", "opus", ...); null is Claude Code's own.
    model: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)] | None = None
    effort: Effort | None = None
    permission_mode: PermissionMode = "default"
    mode: SessionMode = "in_place"


class ModulesSettings(_Strict):
    enabled: list[str] = Field(default_factory=list[str])


# "HH:MM", 24 hour clock, in the daemon's local time zone.
_CLOCK_TIME = r"^([01][0-9]|2[0-3]):[0-5][0-9]$"
_HTTP_URL = r"^https?://[^/\s]+(/\S*)?$"


class NotificationKinds(_Strict):
    """Which `notify` kinds reach the phone. The inbox shows everything regardless."""

    needs_approval: bool = True
    question: bool = True
    review_ready: bool = True
    failed: bool = True
    finished: bool = True
    # Pull request checks; shown in the inbox, pushed only when switched on (D034).
    ci_failed: bool = False
    ready_to_merge: bool = False
    # A session looks stuck; shown in the inbox, pushed only when switched on (D036).
    stuck: bool = False


class QuietHours(_Strict):
    """No notifications are sent from `start` until `end`; it may wrap past midnight."""

    start: str = Field(pattern=_CLOCK_TIME)
    end: str = Field(pattern=_CLOCK_TIME)

    @model_validator(mode="after")
    def _not_empty(self) -> "QuietHours":
        if self.start == self.end:
            msg = "quiet hours start and end must differ"
            raise ValueError(msg)
        return self


class NtfySettings(_Strict):
    """Optional ntfy channel. Anyone who knows a public topic can read it (see README)."""

    enabled: bool = False
    server: str = Field(default="https://ntfy.sh", pattern=_HTTP_URL)
    topic: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,64}$")
    # The address the phone opens harness at, such as "https://mac.tailnet.ts.net", so a
    # tapped ntfy notification opens the item. Without it, notifications carry no link.
    click_base_url: str | None = Field(default=None, pattern=_HTTP_URL)

    @model_validator(mode="after")
    def _topic_when_enabled(self) -> "NtfySettings":
        if self.enabled and self.topic is None:
            msg = "an enabled ntfy channel needs a topic"
            raise ValueError(msg)
        return self


class NotificationSettings(_Strict):
    kinds: NotificationKinds = Field(default_factory=NotificationKinds)
    quiet_hours: QuietHours | None = None
    ntfy: NtfySettings = Field(default_factory=NtfySettings)
    # The contact push services see in the VAPID token: a mailto: address or an https URL.
    # Apple rejects localhost addresses.
    vapid_subject: str = Field(
        default="mailto:harness@example.com", pattern=r"^(mailto:[^\s@]+@[^\s@]+|https://\S+)$"
    )


class UsageSettings(_Strict):
    # How often a minimal probe refreshes the usage windows while a client is visible (D031);
    # 0 turns the refresh off.
    refresh_minutes: int = Field(default=3, ge=0, le=1440)


class StuckSettings(_Strict):
    """When a session counts as stuck (D036); 0 turns that check off."""

    # Waiting on a permission prompt, question or plan for this many minutes.
    waiting_minutes: int = Field(default=15, ge=0, le=1440)
    # Running without any new output for this many minutes.
    silent_minutes: int = Field(default=10, ge=0, le=1440)
    # The same tool call (same tool, same input) made more than this many times in a row.
    repeated_calls: int = Field(default=4, ge=0, le=1000)
    # One turn running for this many minutes.
    turn_minutes: int = Field(default=60, ge=0, le=1440)


class Settings(_Strict):
    server: ServerSettings = Field(default_factory=ServerSettings)
    agents: AgentDefaults = Field(default_factory=AgentDefaults)
    modules: ModulesSettings = Field(default_factory=ModulesSettings)
    notifications: NotificationSettings = Field(default_factory=NotificationSettings)
    usage: UsageSettings = Field(default_factory=UsageSettings)
    stuck: StuckSettings = Field(default_factory=StuckSettings)


class WorktreeConfig(_Strict):
    # True or false makes new chats of this repo use a worktree or not; unset follows
    # `[agents] default_mode` (D038).
    default: bool | None = None
    link: list[str] = Field(default_factory=list[str])
    setup: list[str] = Field(default_factory=list[str])
    # Applies to each setup command separately.
    setup_timeout_seconds: int = Field(default=900, ge=1)

    @field_validator("link")
    @classmethod
    def _links_stay_inside_repo(cls, links: list[str]) -> list[str]:
        for link in links:
            path = PurePosixPath(link)
            if not link or path.is_absolute() or ".." in path.parts or path == PurePosixPath():
                msg = f"link {link!r} must be a relative path inside the repository"
                raise ValueError(msg)
        return links


class RepoConfig(_Strict):
    # The name doubles as the config file name, so it must be a safe file name.
    name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    path: Path
    # False for a plain folder outside any git work tree (D041); files without it are repos.
    git: bool = True
    # None for a plain folder.
    default_branch: str | None = "main"
    # The only URL harness pushes origin to: recorded at registration or confirmed by the
    # user, so an agent cannot redirect an approved push by editing the git config (D050).
    remote_url: str | None = None
    worktree: WorktreeConfig = Field(default_factory=WorktreeConfig)

    @model_validator(mode="after")
    def _plain_folders_have_no_branch(self) -> "RepoConfig":
        if not self.git:
            self.default_branch = None
        return self


class TaskTemplate(_Strict):
    name: str
    prompt: str
    repo: str | None = None
    model: str | None = None
    effort: Effort | None = None
    permission_mode: PermissionMode | None = None
