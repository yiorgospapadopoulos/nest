"""Typed models for the TOML files in the user config directory."""

import re
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StringConstraints,
    field_validator,
    model_validator,
)

Effort = Literal["low", "medium", "high", "xhigh", "max"]
PermissionMode = Literal["default", "acceptEdits", "bypassPermissions", "plan", "auto"]
# The modes an approved plan may continue in; `auto` only with a model that supports it.
PlanApprovalMode = Literal["acceptEdits", "default", "auto"]
type SessionMode = Literal["worktree", "in_place"]
# A pixie's sprite and colour (D072); a project's icon reuses them (B36).
type Mascot = Literal[
    "invader", "ghost", "cat", "owl", "robot", "frog", "mushroom", "bunny", "crab", "sprout"
]
type Color = Annotated[str, StringConstraints(pattern=r"^#[0-9A-Fa-f]{6}$")]
# Which Nest tools a pixie gets (stage 3); every level includes the ones before it.
type Autonomy = Literal["observe", "message", "start", "answer"]
# What a pixie may do with its projects' files: edit them like any chat, only read them,
# or neither (its workdir only).
type ProjectAccess = Literal["edit", "read", "none"]
# What a pixie reports, from the least to the most urgent (B42).
type Severity = Literal["info", "warn", "action"]
# How many chats a pixie may have started and running at once, and start per local day.
type MaxRunning = Annotated[int, Field(ge=1, le=20)]
type MaxPerDay = Annotated[int, Field(ge=1, le=100)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


_HOST_PATTERN = r"(\*\.)?[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*"


class ServerSettings(_Strict):
    # The host is always 127.0.0.1 (D014), so only the port is configurable.
    port: int = Field(default=8765, ge=1, le=65535)
    # Browser origins allowed to open the event socket besides the daemon's own host,
    # such as "https://mac.tailnet.ts.net".
    allowed_origins: list[str] = Field(default_factory=list[str])
    # Host names requests may be addressed to besides 127.0.0.1, localhost, [::1] and
    # *.ts.net (H-02), such as "nest.home.arpa" or "*.example.org"; no port.
    allowed_hosts: list[str] = Field(default_factory=list[str])

    @field_validator("allowed_hosts")
    @classmethod
    def _host_names(cls, hosts: list[str]) -> list[str]:
        for host in hosts:
            if re.fullmatch(_HOST_PATTERN, host) is None:
                msg = f"not a host name or *.domain pattern: {host!r}"
                raise ValueError(msg)
        return [host.lower() for host in hosts]


class AgentDefaults(_Strict):
    model: str | None = None
    effort: Effort | None = None
    # None is Claude Code's own setting: no mode is passed, so your `defaultMode` applies.
    permission_mode: PermissionMode | None = None
    # Where new chats work; a repo's `[worktree] default` overrides it when set (D038).
    default_mode: SessionMode = "in_place"
    # Idle agent processes are closed after this long and resumed on the next message.
    idle_close_minutes: int = Field(default=60, ge=1)


class AgentChoices(_Strict):
    """The agent defaults clients edit: `GET/PUT /api/agents/defaults` (D038)."""

    # A value of the engine's model list ("default", "opus", ...); null is Claude Code's own.
    model: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)] | None = None
    effort: Effort | None = None
    # Null is Claude Code's own setting (its `defaultMode`).
    permission_mode: PermissionMode | None = None
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
    # A pixie's report at or above `pixie_report_level` (B42, D109).
    pixie_report: bool = True
    # A chat paused at the usage limit; it goes on by itself after the reset (B78).
    usage_limit: bool = True


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
    # Long enough to be hard to guess, since the topic is all that protects it.
    topic: str | None = Field(
        default=None, min_length=16, max_length=64, pattern=r"^[A-Za-z0-9_-]+$"
    )
    # The address the phone opens Nest at, such as "https://mac.tailnet.ts.net", so a
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
    # The lowest severity of every pixie's reports that reaches the phone (D109).
    pixie_report_level: Severity = "action"
    quiet_hours: QuietHours | None = None
    ntfy: NtfySettings = Field(default_factory=NtfySettings)
    # The contact push services see in the VAPID token: a mailto: address or an https URL.
    # Apple rejects localhost addresses.
    vapid_subject: str = Field(
        default="mailto:nest@example.com", pattern=r"^(mailto:[^\s@]+@[^\s@]+|https://\S+)$"
    )


class UsageSettings(_Strict):
    # How often a minimal probe refreshes the usage windows while a client is visible (D031);
    # 0 turns the refresh off.
    refresh_minutes: int = Field(default=3, ge=0, le=1440)
    # Publish `usage.warning` once per window period when a window reaches this percent;
    # null (0 in the file, since TOML has no null) turns the warning off (D104).
    warn_percent: int | None = Field(default=80, ge=50, le=99)
    # The warning also reaches the phone as a notification.
    warn_notify: bool = True

    @field_validator("warn_percent", mode="before")
    @classmethod
    def _zero_is_off(cls, value: object) -> object:
        return None if value == 0 else value


class StorageSettings(_Strict):
    # Nest chats not updated for this many days are archived; null never (D104).
    archive_after_days: int | None = Field(default=None, ge=1, le=3650)


class ArtifactSettings(_Strict):
    """What artifact pages may ask Claude (B88, D118): small text tasks, one call each, no
    tools, at most `ask_daily_limit` a day per artifact, answers of about
    `ask_max_output_tokens`.
    """

    ask: StrictBool = True
    ask_model: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)] = "haiku"
    ask_daily_limit: int = Field(default=20, ge=1, le=200)
    ask_max_output_tokens: int = Field(default=1000, ge=100, le=4000)


# `[pixies]` keys before B85: `report_push` moved to `[notifications]
# pixie_report_level`, `projects` went (every pixie works in every project).
_REMOVED_PIXIE_KEYS = ("projects", "report_push")


class PixieDefaults(_Strict):
    """What new pixies start with, and the habit rules of every pixie (D104)."""

    # Null: the agent defaults' model.
    model: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)] | None = None
    autonomy: Autonomy = "observe"
    project_access: ProjectAccess = "edit"
    max_running: MaxRunning = 2
    max_per_day: MaxPerDay = 5
    # Scheduled and triggered habit runs are skipped while set; Run now still runs.
    habits_paused: bool = False
    # Scheduled and triggered runs are skipped while a usage window is this full.
    habit_usage_percent: int = Field(default=80, ge=50, le=100)

    @model_validator(mode="before")
    @classmethod
    def _ignore_removed(cls, data: object) -> object:
        """Keys from before B85 (D109), sent by older clients: ignored, not refused."""
        if not isinstance(data, dict):
            return data
        items = cast("dict[str, object]", data).items()
        return {key: value for key, value in items if key not in _REMOVED_PIXIE_KEYS}


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


class ProjectSettings(_Strict):
    # Project names in the order clients show them, set by reordering the Mac app's tabs
    # (D090); projects not listed follow in file name order.
    order: list[str] = Field(default_factory=list[str])


class Settings(_Strict):
    server: ServerSettings = Field(default_factory=ServerSettings)
    agents: AgentDefaults = Field(default_factory=AgentDefaults)
    modules: ModulesSettings = Field(default_factory=ModulesSettings)
    notifications: NotificationSettings = Field(default_factory=NotificationSettings)
    usage: UsageSettings = Field(default_factory=UsageSettings)
    stuck: StuckSettings = Field(default_factory=StuckSettings)
    projects: ProjectSettings = Field(default_factory=ProjectSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    pixies: PixieDefaults = Field(default_factory=PixieDefaults)
    artifacts: ArtifactSettings = Field(default_factory=ArtifactSettings)

    @model_validator(mode="before")
    @classmethod
    def _move_report_push(cls, data: object) -> object:
        """A settings.toml from before B85 keeps its `[pixies] report_push` as
        `[notifications] pixie_report_level`, unless that is set already (D109).
        """
        if not isinstance(data, dict):
            return data
        settings = cast("dict[str, object]", data)
        pixies = settings.get("pixies")
        notifications = settings.get("notifications", {})
        if not isinstance(pixies, dict) or not isinstance(notifications, dict):
            return settings
        level = cast("dict[str, object]", pixies).get("report_push")
        section = cast("dict[str, object]", notifications)
        if level is None or "pixie_report_level" in section:
            return settings
        return settings | {"notifications": section | {"pixie_report_level": level}}


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
            if (
                not link
                or path.is_absolute()
                or ".." in path.parts
                or path == PurePosixPath()
                # In a worktree `.git` is a file git owns (BUG-96).
                or path.parts[0] == ".git"
            ):
                msg = f"link {link!r} must be a relative path inside the repository, outside .git"
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
    # The only URL Nest pushes origin to: recorded at registration or confirmed by the
    # user, so an agent cannot redirect an approved push by editing the git config (D050).
    remote_url: str | None = None
    # A pixie sprite shown as the project's icon; None shows its initials (B36).
    icon: Mascot | None = None
    # None is the default colour.
    icon_color: Color | None = None
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
