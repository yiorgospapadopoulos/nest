"""Provider-neutral agent types, so engines other than Claude (Codex) can plug in later."""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal, Protocol, get_args

from pydantic import BaseModel, Field, JsonValue

from nestd.config.models import Effort, PermissionMode


class TextBlock(BaseModel):
    type: Literal["text"] = "text"
    text: str


class ThinkingBlock(BaseModel):
    type: Literal["thinking"] = "thinking"
    # Empty when the engine left the thinking out (redacted or omitted).
    text: str
    # From the block's start to its end in the engine's stream; None when unknown (D045).
    duration_ms: int | None = None


class ToolUseBlock(BaseModel):
    type: Literal["tool_use"] = "tool_use"
    id: str
    name: str
    input: dict[str, JsonValue]


class ResultImage(BaseModel):
    """An image a tool returned, kept as a session attachment the clients fetch (B59)."""

    attachment_id: str
    media_type: str


class ImageData(BaseModel):
    """An image as the engine returned it in a tool result: its base64 data."""

    media_type: str
    data: str


def _no_images(images: list[ResultImage]) -> bool:
    return not images


def _none(value: object) -> bool:
    return value is None


class ToolResultBlock(BaseModel):
    type: Literal["tool_result"] = "tool_result"
    tool_use_id: str
    content: str
    is_error: bool = False
    # Images in the result (a Read of a PNG, a screenshot tool) once the session stored
    # them (B59); left out of the payload when there are none.
    images: list[ResultImage] = Field(default_factory=list[ResultImage], exclude_if=_no_images)
    # The images as the engine returned them, until the session stores them; never sent.
    image_data: list[ImageData] = Field(default_factory=list[ImageData], exclude=True)


type MessageBlock = TextBlock | ThinkingBlock | ToolUseBlock | ToolResultBlock

# What the engine notes in its transcript besides messages: the context was compacted or
# cleared, it switched to a fallback model, or it retries a failed API request.
# `command_output`: what a local slash command (/cost, /context...) answered, without the model.
# `files_restored`: the user restored files to before one of their messages (IMP-02).
type NoticeKind = Literal[
    "compacted", "cleared", "model_fallback", "api_retry", "command_output", "files_restored"
]


class TokenUsage(BaseModel):
    """Tokens one turn used; components the engine did not report count as zero."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0


class ResultInfo(BaseModel):
    """The end of one turn."""

    is_error: bool
    subtype: str
    duration_ms: int
    num_turns: int
    errors: list[str]
    tokens: TokenUsage = Field(default_factory=TokenUsage)


class HookOutput(BaseModel):
    """What a hook from the user's setup said when it finished, for the transcript (B59)."""

    hook_id: str | None = None
    # The hook's event and what it matched, such as `PostToolUse:Edit`.
    hook_name: str
    # The event, such as `PreToolUse`, `PostToolUse`, `Stop` or `SessionStart`.
    hook_event: str
    outcome: Literal["success", "error", "cancelled"]
    exit_code: int | None = None
    # The message the hook has for the user (its JSON `systemMessage`).
    system_message: str | None = None
    # What else it printed for the user: its plain output, or why it failed.
    output: str | None = None


class UsageWindow(BaseModel):
    utilization: float
    resets_at: datetime | None


class UsageInfo(BaseModel):
    """Subscription usage: the five-hour and seven-day windows, when reported."""

    five_hour: UsageWindow | None
    seven_day: UsageWindow | None


# The usage window whose limit was reached (B78), as the engine names it.
type LimitWindow = Literal[
    "five_hour", "seven_day", "seven_day_opus", "seven_day_sonnet", "overage"
]
LIMIT_WINDOWS: frozenset[str] = frozenset(get_args(LimitWindow.__value__))


class LimitHit(BaseModel):
    """The subscription's usage limit was reached during the run (B78). The engine says so
    with an event that may name the window and its reset time, and the message it cuts
    off carries a rate limit error (`cut_off`); either may come first.
    """

    window: LimitWindow | None = None
    resets_at: datetime | None = None
    cut_off: bool = False

    def merged(self, earlier: "LimitHit | None") -> "LimitHit":
        """This report with what an earlier one of the same turn knew and this one does not."""
        if earlier is None:
            return self
        return LimitHit(
            window=self.window or earlier.window,
            resets_at=self.resets_at or earlier.resets_at,
            cut_off=self.cut_off or earlier.cut_off,
        )


class AgentTask(BaseModel):
    """A step in the life of a task the engine runs beside the turn: a subagent or a command.

    A background task's tool call returns at once; its real end arrives later as `finished`.
    """

    task_id: str
    # started; backgrounded (a foreground task moved to the background); finished.
    phase: Literal["started", "backgrounded", "finished"]
    # The tool call that started it (an Agent or Bash call), when the engine says.
    tool_use_id: str | None = None
    # The engine's kind of task, such as `local_agent` or `local_bash`.
    task_type: str | None = None
    description: str | None = None
    # Started in the background rather than blocking its tool call.
    background: bool = False
    # How a finished task ended.
    status: Literal["completed", "failed", "stopped"] | None = None
    # A finished subagent's report, when the engine's notification has one (B46); left out
    # of the event otherwise.
    summary: str | None = Field(default=None, exclude_if=_none)


class SlashCommand(BaseModel):
    """A command the user can type as "/name": built in, from the user's setup, or a skill."""

    name: str
    description: str | None = None
    argument_hint: str | None = None


class AgentInfo(BaseModel):
    """A subagent type the engine offers."""

    name: str
    description: str | None = None


class CommandCatalog(BaseModel):
    """The slash commands and agents of a run, sorted by name."""

    commands: list[SlashCommand] = Field(default_factory=list[SlashCommand])
    agents: list[AgentInfo] = Field(default_factory=list[AgentInfo])
    # Names only, completing the known list rather than replacing it.
    partial: bool = False


class ContextUsage(BaseModel):
    """How full the agent's context window is."""

    # Percent of the limit used, 0 to 100.
    percent: float
    used: int
    limit: int


class ModelOption(BaseModel):
    """A model the engine offers, in the engine's own order (D038)."""

    # What a session's `model` is set to, such as "default", "opus" or "claude-opus-4-8".
    value: str
    display_name: str
    description: str
    # The thinking levels the model takes; empty when it takes none (Haiku).
    effort_levels: list[str] = Field(default_factory=list[str])
    supports_effort: bool = False
    # Whether the model can run in the `auto` permission mode (IMP-06).
    supports_auto_mode: bool = False
    # The model id the engine resolves `value` to, such as "claude-opus-5-5" for "opus".
    resolved_model: str | None = None
    # The thinking level Claude Code uses for this model when none is chosen, from your
    # Claude Code settings (IMP-07); None when they set none. Read when served, not stored.
    claude_code_effort: str | None = None


class AccountInfo(BaseModel):
    """Who the engine is signed in as. The email is shown only when the user asks."""

    display_name: str | None = None
    email: str | None = None
    # A readable plan name, such as "Claude Max".
    plan: str | None = None
    organization: str | None = None


class EngineDetails(BaseModel):
    """What the engine reports about itself when it starts; a part it left out is None."""

    models: list[ModelOption] | None = None
    account: AccountInfo | None = None


@dataclass(frozen=True)
class McpServer:
    """An MCP server (or claude.ai connector) the agent's engine loaded, with its status."""

    name: str
    status: str
    # Why it failed, when the engine says.
    error: str | None = None


class ToolRefusedError(Exception):
    """A Nest tool declined the call; the agent sees the message as the tool's error."""


@dataclass(frozen=True)
class AgentTool:
    """A tool the daemon offers the agent in-process, such as a pixie's memory (D072)."""

    name: str
    description: str
    # JSON Schema of the input object.
    schema: dict[str, JsonValue]
    # Returns the text the agent sees; raises ToolRefusedError to refuse.
    handler: Callable[[dict[str, JsonValue]], Awaitable[str]]


@dataclass(frozen=True)
class Subagent:
    """A subagent the run's agent can call by name, such as a pixie (B40). Left out
    (None or empty): the calling chat's model and thinking, and every skill and tool.
    """

    description: str
    prompt: str
    permission_mode: PermissionMode
    model: str | None = None
    effort: Effort | None = None
    skills: tuple[str, ...] = ()
    # Permission rules for tools it never gets.
    disallowed_tools: tuple[str, ...] = ()


# The tools that call a subagent; "Task" is the name in older Claude Code versions.
AGENT_TOOLS = frozenset({"Agent", "Task"})


@dataclass(frozen=True)
class CallRules:
    """Which agents of a run may call which pixies as subagents (B70). Ordinary subagents
    are never limited.
    """

    # The subagent names that are pixies.
    pixies: frozenset[str] = frozenset()
    # The pixies the run's main agent may call.
    main: frozenset[str] = frozenset()
    # By pixie, the pixies it may call: only a team's leader has any, its own members.
    leaders: Mapping[str, frozenset[str]] = field(default_factory=dict[str, frozenset[str]])

    def may_call(self, caller: str | None, target: str) -> bool:
        """`caller` is None for the main agent, else the calling subagent's name."""
        if target not in self.pixies:
            return True
        allowed = self.main if caller is None else self.leaders.get(caller, frozenset())
        return target in allowed


@dataclass(frozen=True)
class SessionSpec:
    cwd: Path
    # None passes no mode, so Claude Code's own setting (`defaultMode`) applies (IMP-06).
    permission_mode: PermissionMode | None
    model: str | None = None
    effort: Effort | None = None
    # The engine's own session id to continue a previous conversation.
    resume_id: str | None = None
    extra_dirs: tuple[Path, ...] = ()
    system_prompt_append: str | None = None
    # Nest tools for this run, served in-process (D072).
    tools: tuple[AgentTool, ...] = ()
    # Nest tools of every chat and pixie run, such as the artifact tools (B79), served
    # in-process as their own server. Unlike `tools` its subagents may use them too.
    nest_tools: tuple[AgentTool, ...] = ()
    # When set, file edits outside this folder are denied, in every permission mode.
    write_root: Path | None = None
    # Claude Code skill names for this run; empty leaves Claude Code's default (all).
    skills: tuple[str, ...] = ()
    # Subagents by the name the agent calls them with; fixed for the run's life (B40).
    subagents: Mapping[str, Subagent] = field(default_factory=dict[str, Subagent])
    # Which agents may call which pixies among the subagents; None guards no calls (B70).
    call_rules: CallRules | None = None
    # Commits, pushes and pull request writes blocked, and git and gh without credentials
    # (D013): pixie chats, habit runs and chats a pixie started (D072). A normal chat uses
    # git and gh as in the terminal, with the user's own login (B58).
    guard_git: bool = True
    # With `resume_id`: load the conversation only up to and including this entry, into a
    # new engine session (a fork), leaving the resumed one as it was (B59).
    resume_at: str | None = None
    # With `resume_at`: the user message whose turn the cut drops. The engine refuses the
    # resume when anything after `resume_at` is not that turn's (B59).
    drops_turn: str | None = None


@dataclass(frozen=True)
class ImageInput:
    media_type: str
    data: str  # base64


@dataclass(frozen=True)
class UserInput:
    text: str
    images: tuple[ImageInput, ...] = ()
    # Other attachments; the agent reads them from these absolute paths.
    file_paths: tuple[Path, ...] = ()


@dataclass(frozen=True)
class PermissionRequest:
    tool_name: str
    tool_input: dict[str, JsonValue]
    # The engine's own sentence for the prompt, when it provides one.
    title: str | None = None
    # Why the engine asks, such as a hook's reason or the path outside the allowed folders.
    reason: str | None = None
    # What "Always allow" allows, in words such as `Bash(npm test:*)`: the rule the engine
    # suggests, else that exact call (B59). None when a provider has no rule to offer, and
    # "always" then allows the tool by name (IMP-06).
    always_rule: str | None = None


@dataclass(frozen=True)
class PermissionDecision:
    behavior: Literal["allow", "deny"]
    message: str | None = None
    # The user chose "Always allow": the engine applies the rules it suggested.
    always: bool = False


@dataclass(frozen=True)
class QuestionOption:
    label: str
    description: str | None = None
    # The option the agent prefers.
    recommended: bool = False


@dataclass(frozen=True)
class Question:
    question: str
    header: str | None
    options: tuple[QuestionOption, ...]
    multi_select: bool


@dataclass(frozen=True)
class QuestionRequest:
    """Questions the agent asks the user, each answered with an option or free text."""

    questions: tuple[Question, ...]
    tool_use_id: str | None = None


@dataclass(frozen=True)
class QuestionAnswer:
    # Question text to the answer; None when the user dismissed the questions.
    answers: dict[str, str] | None
    message: str | None = None


@dataclass(frozen=True)
class PlanRequest:
    """The agent finished a plan in plan mode and asks to start working on it."""

    plan: str
    tool_use_id: str | None = None


@dataclass(frozen=True)
class PlanDecision:
    approved: bool
    # The permission mode the agent continues in after an approval.
    mode: PermissionMode | None = None
    # What the agent is told when the plan is not approved.
    message: str | None = None


class RewindResult(BaseModel):
    """Restoring files to before a user message, previewed or done (IMP-02)."""

    can_rewind: bool
    files_changed: list[str] = Field(default_factory=list[str])
    insertions: int = 0
    deletions: int = 0
    # Why the files cannot be restored, in the engine's words.
    error: str | None = None


@dataclass(frozen=True)
class ForkPoint:
    """Where a conversation is cut to before one of its user messages (B59)."""

    # The engine's last transcript entry to keep; None when the message began the
    # conversation, so nothing is kept.
    keep_through: str | None


class ApprovalHandler(Protocol):
    """Where an agent run takes what needs the user: tool permissions, questions and plans."""

    async def decide(self, request: PermissionRequest) -> PermissionDecision: ...

    async def ask(self, request: QuestionRequest) -> QuestionAnswer: ...

    async def review_plan(self, request: PlanRequest) -> PlanDecision: ...


class ProviderEventSink(Protocol):
    """Where a running agent reports everything it does, for the whole life of the run.

    Output can arrive without a user message: an agent may start a turn on its own, for
    example when a background task it launched finishes. `result` ends every turn.
    """

    async def message(self, blocks: list[MessageBlock], parent_tool_use_id: str | None) -> None: ...

    async def text_delta(self, text: str) -> None: ...

    async def thinking(self, active: bool) -> None:
        """The main agent started (True) or finished (False) a thinking block (D045)."""
        ...

    async def thinking_delta(self, text: str, parent_tool_use_id: str | None) -> None:
        """Thinking text as it is written, by the main agent or a subagent (B59)."""
        ...

    async def subagent_delta(self, text: str, parent_tool_use_id: str) -> None:
        """A subagent's text as it is written, under the tool call that started it (B59)."""
        ...

    async def hook(self, output: HookOutput) -> None:
        """A hook finished with something to show the user, even between turns (B59)."""
        ...

    async def result(self, info: ResultInfo) -> None: ...

    async def usage(self, info: UsageInfo) -> None: ...

    async def limit_hit(self, hit: LimitHit) -> None:
        """The usage limit was reached: the engine refuses requests until it resets (B78)."""
        ...

    async def provider_session_id(self, session_id: str) -> None: ...

    async def connectors(self, servers: list[McpServer]) -> None:
        """The MCP servers the engine loaded for this run, reported when it starts.

        Most are still connecting then; `AgentRun.connector_statuses` has the settled ones.
        """
        ...

    async def commands(self, catalog: CommandCatalog) -> None:
        """The slash commands and agents the run offers, reported when it starts."""
        ...

    async def engine_details(self, details: EngineDetails) -> None:
        """The models and account the engine reported when the run started (D038)."""
        ...

    async def background_tasks(self, running: int) -> None:
        """How many background tasks the agent has running, reported when it changes."""
        ...

    async def task(self, update: AgentTask) -> None:
        """A task started, moved to the background or finished, even between turns.

        Tasks still running when the run ends are reported finished as `stopped`.
        """
        ...

    async def stopped(self, error: str) -> None:
        """The agent process ended on its own; the run is unusable and already closed."""
        ...

    async def notice(self, kind: NoticeKind, text: str) -> None:
        """Something the engine notes in its transcript, in words for the user."""
        ...

    async def permission_mode(self, mode: PermissionMode) -> None:
        """The engine reported its permission mode: at a turn's start, or a switch it made."""
        ...

    async def checkpoint(self, checkpoint_id: str) -> None:
        """The engine took the user message just sent, under this id: files can be
        restored to how they were before it (IMP-02).
        """
        ...

    async def message_taken(self, message_id: str, checkpoint_id: str) -> None:
        """The engine read a message written into the running turn (`AgentRun.steer`): at
        a step of that turn, or as the start of its next one. `checkpoint_id` is its id
        in the engine's transcript (B59).
        """
        ...


class AgentRun(Protocol):
    """A live agent process for one session."""

    # Whether messages can be written into a running turn (`steer`); a provider that
    # cannot gets them after the turn instead (B59).
    steers: bool

    async def send(self, user_input: UserInput) -> None:
        """Submit a user message; what the agent does comes through the sink."""
        ...

    async def steer(self, user_input: UserInput, message_id: str) -> None:
        """Write a message into the running turn. The engine reads it at its next step
        (after a tool call) or, when the turn ends first, starts its next turn with it;
        either way the sink hears `message_taken(message_id, ...)` (B59).
        """
        ...

    async def withdraw(self, message_id: str) -> bool:
        """Take back a steered message the engine has not read yet. False when it already
        has (or is about to): it will be or was echoed (B59).
        """
        ...

    async def interrupt(self) -> None: ...

    async def set_model(self, model: str | None) -> None: ...

    async def set_permission_mode(self, mode: PermissionMode) -> None: ...

    async def connector_statuses(self) -> list[McpServer]:
        """The live status of the run's MCP servers and connectors."""
        ...

    async def context_usage(self) -> ContextUsage | None:
        """How full the context window is now; None when the engine does not say."""
        ...

    async def rewind_files(self, checkpoint_id: str, dry_run: bool) -> RewindResult:
        """Restore the files the agent changed since the user message `checkpoint_id` to
        how they were before it, or with `dry_run` only say what that would change. The
        conversation stays as it is.
        """
        ...

    async def stop_task(self, task_id: str) -> bool:
        """Stop one running task (a background command or a subagent), named by its task
        id or the id of the tool call that started it, without stopping the turn; its end
        is reported as a task update. False when no such task runs (B59).
        """
        ...

    async def close(self) -> None:
        """Stop the agent and wait for its process (and its exit hooks) to finish."""
        ...


class AgentProvider(Protocol):
    @property
    def name(self) -> str: ...

    async def open(
        self, spec: SessionSpec, handler: ApprovalHandler, sink: ProviderEventSink
    ) -> AgentRun: ...

    async def fork_point(self, cwd: Path, session_id: str, message_id: str) -> ForkPoint | None:
        """Where the engine session `session_id`, run in `cwd`, is cut to before its user
        message `message_id` (a checkpoint id); None when its transcript lacks it (B59).
        """
        ...
