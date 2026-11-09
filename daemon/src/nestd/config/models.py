"""Typed models for the TOML files in the user config directory."""

import re
from pathlib import Path, PurePosixPath
from typing import Annotated, Final, Literal, cast

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictBool,
    StringConstraints,
    field_validator,
    model_validator,
)

from nestd.triggers.models import ChatTrigger

Effort = Literal["low", "medium", "high", "xhigh", "max"]
PermissionMode = Literal["default", "acceptEdits", "bypassPermissions", "plan", "auto"]
# How many tokens a chat's context holds before its engine compacts it by itself (B146), in
# Claude Code's range; None leaves it to the engine. Each model uses the smaller of this and
# its own window.
type CompactAt = Annotated[int, Field(ge=100_000, le=1_000_000)]
# The modes an approved plan may continue in; `auto` only with a model that supports it.
PlanApprovalMode = Literal["acceptEdits", "default", "auto"]
type SessionMode = Literal["worktree", "in_place"]
# The names of the sprites before the fairy redesign (B89), still accepted when read so
# older clients and saved project icons keep working; only the new names are written.
MASCOT_RENAMES: Final = {
    "invader": "frost",
    "ghost": "brook",
    "cat": "bluebell",
    "owl": "moth",
    "robot": "star",
    "frog": "dragonfly",
    "mushroom": "rose",
    "bunny": "nightshade",
    "crab": "firefly",
    "sprout": "sprig",
}


def _renamed_mascot(value: object) -> object:
    return MASCOT_RENAMES.get(value, value) if isinstance(value, str) else value


# A pixie's sprite and colour (D072, B89); a project's icon reuses them (B36).
type Mascot = Annotated[
    Literal[
        "bluebell",
        "dragonfly",
        "moth",
        "firefly",
        "rose",
        "frost",
        "sprig",
        "nightshade",
        "brook",
        "star",
    ],
    BeforeValidator(_renamed_mascot),
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


def _worktree_folder(value: object) -> object:
    """A folder for worktrees: absolute, or under the home folder with `~` (B141)."""
    if not isinstance(value, str):
        return value
    folder = value.strip()
    if not Path(folder).expanduser().is_absolute() or "\0" in folder:
        msg = f"the worktrees folder {value!r} must be an absolute path or start with ~"
        raise ValueError(msg)
    return folder


_PREFIX_CHARACTERS = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,39}")


def _branch_prefix(value: object) -> object:
    """The start of a branch name, such as "agent/" or "gp-": letters, digits and . _ - /
    in parts git takes for a branch; empty for none (B141).
    """
    if not isinstance(value, str) or not value:
        return value
    parts = value.split("/")
    if (
        _PREFIX_CHARACTERS.fullmatch(value) is None
        or ".." in value
        or any(part.startswith(".") or part.endswith(".lock") for part in parts)
        or "" in parts[:-1]
    ):
        msg = f"{value!r} cannot start a branch name"
        raise ValueError(msg)
    return value


type WorktreeFolder = Annotated[str, BeforeValidator(_worktree_folder)]
type BranchPrefix = Annotated[str, BeforeValidator(_branch_prefix)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _engine_default_is_none(value: object) -> object:
    """The engines' `default` entry is no model Nest offers since B94: an older client
    sending it asks for the default Nest picks, as a null does.
    """
    return None if value == "default" else value


# A model chosen from an engine's list; null (or an older client's "default") is the
# default Nest picks: the engine's default model, by name (B94).
type ModelChoice = Annotated[
    Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)] | None,
    BeforeValidator(_engine_default_is_none),
]
type ProviderName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


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
    """`[agents]`. Since B94 the engine, model, effort and mode are stored as the concrete
    values new chats start with; a file from before has nulls, which the daemon replaces
    once it can resolve them (`ChatDefaults`).
    """

    # The engine new chats run on, such as "claude" or "codex"; null: the first engine
    # Nest saw signed in.
    provider: ProviderName | None = None
    model: ModelChoice = None
    effort: Effort | None = None
    # Null is Ask ("default") since B94; before, Claude Code's own `defaultMode`.
    permission_mode: PermissionMode | None = None
    # Where new chats work; a repo's `[worktree] default` overrides it when set (D038).
    default_mode: SessionMode = "in_place"
    # Where new chats compact by themselves; null: each engine's own (B146).
    compact_at: CompactAt | None = None
    # Idle agent processes are closed after this long and resumed on the next message.
    idle_close_minutes: int = Field(default=60, ge=1)


class AgentChoices(_Strict):
    """The agent defaults clients edit: `GET/PUT /api/agents/defaults` (D038, B94).

    Served concrete: a null model only while no engine reported its list, a null effort
    only for a model without thinking levels (or one not known yet). Sent nulls are the
    defaults Nest picks: the first engine signed in, its default model, Medium (or the
    closest level), Ask.
    """

    provider: ProviderName | None = None
    # A value of the engine's model list, such as "opus" or "gpt-5.5".
    model: ModelChoice = None
    effort: Effort | None = None
    permission_mode: PermissionMode | None = None
    mode: SessionMode = "in_place"
    # Null is each engine's own; left out keeps the stored one (B146).
    compact_at: CompactAt | None = None


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
    # A pixie a chat called stopped for the user's decision (B133).
    pixie_waiting: bool = True
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

    # The Claude model new Claude pixies start on; null (from before B94, or sent by an
    # older client) becomes the agent defaults' model, or Claude's default model.
    model: ModelChoice = None
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


class LimitSettings(_Strict):
    """What Nest lets agents do on their own (D160)."""

    # Whether pixies, subagents and Autopilot may push and open or merge pull requests.
    can_push: bool = False


class ComputerUseSettings(_Strict):
    """`[computer_use]` (B150, D178): whether chats may see and use apps at all; a chat
    still asks the user per app."""

    enabled: bool = False
    # Whether pixie chats, habit runs, chats pixies start and pixies called as subagents
    # may use it.
    pixies: bool = False


class ProjectSettings(_Strict):
    # Project names in the order clients show them, set by reordering the Mac app's tabs
    # (D090); projects not listed follow in file name order.
    order: list[str] = Field(default_factory=list[str])


class McpSharing(_Strict):
    """Whether Nest writes the shared MCP servers into each engine's own config (B97)."""

    claude: bool = True
    codex: bool = True


class ConfigurationSettings(_Strict):
    """Nest's own part of Settings > Configuration (B97); the engines' files hold the rest."""

    mcp_shared: McpSharing = Field(default_factory=McpSharing)
    # Nest switched the Claude-only claude.ai skills off for Codex once, when it first
    # pointed Codex at the shared skills; the user's later choices stay.
    codex_claude_only_off: bool = False


# The highest TCP port.
MAX_PORT = 65535


class PortSettings(_Strict):
    """`[ports]` (B108): each folder a chat works in gets `size` consecutive ports, block
    `index` starting at `start + index * size`, for `blocks` folders at most.
    """

    start: int = Field(default=41000, ge=1024, le=MAX_PORT)
    size: int = Field(default=10, ge=1, le=100)
    blocks: int = Field(default=100, ge=1, le=1000)

    @model_validator(mode="after")
    def _fits_below_max_port(self) -> "PortSettings":
        last = self.start + self.size * self.blocks - 1
        if last > MAX_PORT:
            msg = f"the ports run to {last}, past {MAX_PORT}: lower start, size or blocks"
            raise ValueError(msg)
        return self


class WorktreeDefaults(_Strict):
    """`[worktrees]` (B141): how Nest makes and keeps worktrees, unless a project's
    `[worktree]` says otherwise.
    """

    # None: in each project at `.claude/worktrees`, where Claude Code keeps its own (D028).
    # Else a folder holding one folder per project, named after it.
    folder: WorktreeFolder | None = None
    # Starts the name of each branch Nest names itself.
    branch_prefix: BranchPrefix = "agent/"
    # Remove Nest's worktrees that hold nothing off the base branch and no open chat uses.
    clean_merged: bool = False
    # Check out each new worktree's submodules.
    submodules: bool = False


class Settings(_Strict):
    server: ServerSettings = Field(default_factory=ServerSettings)
    agents: AgentDefaults = Field(default_factory=AgentDefaults)
    modules: ModulesSettings = Field(default_factory=ModulesSettings)
    notifications: NotificationSettings = Field(default_factory=NotificationSettings)
    usage: UsageSettings = Field(default_factory=UsageSettings)
    stuck: StuckSettings = Field(default_factory=StuckSettings)
    limits: LimitSettings = Field(default_factory=LimitSettings)
    computer_use: ComputerUseSettings = Field(default_factory=ComputerUseSettings)
    projects: ProjectSettings = Field(default_factory=ProjectSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    pixies: PixieDefaults = Field(default_factory=PixieDefaults)
    artifacts: ArtifactSettings = Field(default_factory=ArtifactSettings)
    configuration: ConfigurationSettings = Field(default_factory=ConfigurationSettings)
    ports: PortSettings = Field(default_factory=PortSettings)
    worktrees: WorktreeDefaults = Field(default_factory=WorktreeDefaults)

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
    # The project's own choices of `[worktrees]`; None follows it (B141). The folder here
    # holds the project's worktrees itself.
    folder: WorktreeFolder | None = None
    branch_prefix: BranchPrefix | None = None
    clean_merged: bool | None = None
    submodules: bool | None = None

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


# Which open issues the start screen lists: all of them, or those assigned to the user (B101).
type IssueShow = Literal["all", "mine"]


def _mine(value: object) -> object:
    """`assigned` is the setting's earlier name for `mine`."""
    return "mine" if value == "assigned" else value


class IssuesConfig(_Strict):
    show: Annotated[IssueShow, BeforeValidator(_mine)] = "all"


class RunConfig(_Strict):
    """`[run]` (B108): the project's dev server, which the user starts and stops in each
    folder a chat works in.
    """

    command: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    # Start it once a new worktree's setup succeeded.
    after_setup: bool = False


# Chat triggers one project has at most (B148).
MAX_CHAT_TRIGGERS = 20


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
    issues: IssuesConfig = Field(default_factory=IssuesConfig)
    # None: the project has no dev server command, so its chats show no Run control.
    run: RunConfig | None = None
    # `[[triggers]]` (B148): GitHub events that start a chat in the project.
    triggers: Annotated[list[ChatTrigger], Field(max_length=MAX_CHAT_TRIGGERS)] = Field(
        default_factory=list[ChatTrigger]
    )

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
