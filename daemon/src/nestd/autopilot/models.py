from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from nestd.config.models import PermissionMode

# Why a run ended: the agent said it is done, its time or the weekly usage cap ran out, it
# stopped getting anywhere, the engine kept failing, or the user stopped it or switched it off.
type AutopilotEnd = Literal["done", "time", "weekly_cap", "stuck", "errors", "stopped", "off"]
# What Nest settled for the user: a question, a plan, a permission it allowed or one it denied.
type DecisionKind = Literal["question", "plan", "allowed", "denied"]
type WeeklyCap = Literal[50, 60, 70, 80, 90]

_WEEK_MINUTES = 7 * 24 * 60


class AutopilotBudget(BaseModel):
    """What may stop a run earlier than done; both left out, it runs until the task is done."""

    model_config = ConfigDict(extra="forbid")

    stop_after_minutes: Annotated[int, Field(ge=1, le=_WEEK_MINUTES)] | None = None
    # The percentage of the weekly usage window at which the run stops.
    weekly_cap: WeeklyCap | None = None


class SetAutopilot(AutopilotBudget):
    """Turns Autopilot on or off; on a run in progress, a new budget replaces its budget."""

    on: bool


class DecisionOption(BaseModel):
    """An option a question offered."""

    label: str
    description: str | None = None
    picked: bool = False


class AutopilotDecision(BaseModel):
    kind: DecisionKind
    # The question, the plan's first line or the tool call.
    title: str
    # The answer chosen. A denied call stored before `reason` says why here.
    answer: str
    at: datetime
    # What a question offered; empty for a permission or a plan.
    options: list[DecisionOption] = Field(default_factory=list[DecisionOption])
    # Why, in words that come only from what the agent or the engine gave.
    reason: str | None = None
    # A plan's text, cut at `DETAIL_CHARS`.
    detail: str | None = None


class Autopilot(BaseModel):
    """A run in progress."""

    started_at: datetime
    # When the time budget runs out; None without one.
    until: datetime | None = None
    weekly_cap: WeeklyCap | None = None
    # The permission mode the chat goes back to.
    mode: PermissionMode
    follows_claude_code_mode: bool = False
    # Messages Autopilot sent.
    turns: int = 0
    # Turns in a row in which the agent called no tool.
    idle_turns: int = 0
    # Stuck flags answered with a nudge, and the flag answered last.
    nudges: int = 0
    nudged_since: datetime | None = None
    # Failed turns in a row, and when the next try goes.
    errors: int = 0
    retry_at: datetime | None = None
    # What the agent said it finished; the run ends with its turn.
    summary: str | None = None
    decisions: list[AutopilotDecision] = Field(default_factory=list[AutopilotDecision])


class AutopilotReport(BaseModel):
    """What a finished run did; it stays in the chat like a message."""

    started_at: datetime
    ended_at: datetime
    ended: AutopilotEnd
    summary: str | None
    turns: int
    decisions: list[AutopilotDecision]
