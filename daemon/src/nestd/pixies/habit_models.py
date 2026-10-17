"""Habits, their runs and pixies' reports, as the API and the stores see them (B42)."""

from datetime import datetime
from typing import Annotated, Literal, Self, get_args

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    model_validator,
)

from nestd.config.models import Severity

SEVERITIES: tuple[Severity, ...] = ("info", "warn", "action")
# Events on the chats of a pixie's projects that can start a habit.
type Trigger = Literal["stuck", "failed", "review_ready", "ci_failed"]
TRIGGERS: tuple[Trigger, ...] = get_args(Trigger.__value__)
type RunOutcome = Literal[
    "queued", "running", "reported", "quiet", "failed", "stalled", "timed_out", "skipped"
]
# Why a run was started: its schedule, events, or the user's Run now.
type RunKind = Literal["schedule", "trigger", "manual"]

NAME_MAX = 60
PROMPT_MAX = 4000
TITLE_MAX = 120
BODY_MAX = 4000
LINK_MAX = 2000

type HabitName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=NAME_MAX)
]
type HabitPrompt = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=PROMPT_MAX)
]
type MaxMinutes = Annotated[int, Field(ge=1, le=120)]
# "HH:MM", 24 hour clock, local time of the Mac.
type ClockTime = Annotated[str, StringConstraints(pattern=r"^([01][0-9]|2[0-3]):[0-5][0-9]$")]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Hourly(_Strict):
    kind: Literal["hourly"]
    minute: int = Field(ge=0, le=59)


class Daily(_Strict):
    kind: Literal["daily"]
    time: ClockTime


class Weekdays(_Strict):
    """Monday to Friday."""

    kind: Literal["weekdays"]
    time: ClockTime


class Weekly(_Strict):
    kind: Literal["weekly"]
    # Monday is 0.
    weekday: int = Field(ge=0, le=6)
    time: ClockTime


type Schedule = Annotated[Hourly | Daily | Weekdays | Weekly, Field(discriminator="kind")]

NEEDS_A_START = "a habit needs a schedule or at least one trigger"


def _unique(triggers: list[Trigger]) -> list[Trigger]:
    return list(dict.fromkeys(triggers))


class HabitIdea(_Strict):
    """A habit as a pixie suggests it in a card: nothing runs until the user starts it."""

    name: HabitName
    prompt: HabitPrompt
    schedule: Schedule | None = None
    triggers: list[Trigger] = Field(default_factory=list[Trigger])

    @model_validator(mode="after")
    def _starts(self) -> Self:
        self.triggers = _unique(self.triggers)
        if self.schedule is None and not self.triggers:
            raise ValueError(NEEDS_A_START)
        return self


class CreateHabit(HabitIdea):
    max_minutes: MaxMinutes = 20
    enabled: bool = True


class UpdateHabit(_Strict):
    """Fields left out are unchanged; an explicit null `schedule` removes the schedule."""

    name: HabitName | None = None
    prompt: HabitPrompt | None = None
    schedule: Schedule | None = None
    triggers: list[Trigger] | None = None
    max_minutes: MaxMinutes | None = None
    enabled: bool | None = None


class HabitRun(BaseModel):
    id: str
    habit_id: str
    pixie_id: str
    # The run's own session, for its transcript; None until it starts.
    session_id: str | None
    due_at: datetime | None
    started_at: datetime | None
    ended_at: datetime | None
    outcome: RunOutcome
    reason: str | None
    # The title of the run's first report.
    report_title: str | None


class Habit(BaseModel):
    id: str
    pixie_id: str
    name: str
    prompt: str
    schedule: Schedule | None
    triggers: list[Trigger]
    max_minutes: int
    enabled: bool
    created_at: datetime
    updated_at: datetime
    # When the schedule runs it next; None without a schedule or while paused.
    next_due_at: datetime | None
    # The newest run that is not waiting in the queue.
    last_run: HabitRun | None


class PixieReport(BaseModel):
    id: str
    pixie_id: str
    severity: Severity
    title: str
    body: str
    link: str | None
    habit_id: str | None
    # The habit's name when it reported.
    habit_name: str | None
    run_id: str | None
    created_at: datetime
    read_at: datetime | None


class ReadReports(BaseModel):
    """The reports a request marked read."""

    ids: list[str]


def severity_at_least(severity: Severity, minimum: Severity) -> bool:
    return SEVERITIES.index(severity) >= SEVERITIES.index(minimum)


def problems(error: ValidationError) -> str:
    """A validation error in words for a pixie's tool result."""
    parts: list[str] = []
    for item in error.errors():
        where = ".".join(str(part) for part in item["loc"])
        message = item["msg"].removeprefix("Value error, ")
        parts.append(f"{where}: {message}" if where else message)
    return "; ".join(parts) + "."
