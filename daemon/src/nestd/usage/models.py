from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, computed_field

from nestd.providers.base import TokenUsage, window_label

type PeriodUnit = Literal["day", "week", "month", "year"]


@dataclass(frozen=True)
class Turn:
    """One recorded row: a main-chat turn, or a subagent's API reply."""

    at: datetime
    session_id: str
    repo: str
    subagent: bool
    tokens: TokenUsage
    # The engine the chat ran on (B91).
    provider: str = "claude"


class TokenTotals(TokenUsage):
    # All four components together.
    total: int = 0


class BarUsage(BaseModel):
    # The local start of the bar's hour, day or month, with its UTC offset.
    start: datetime
    tokens: int
    sessions: int


class ProjectUsage(BaseModel):
    name: str
    tokens: int
    # Every pixie chat together, under the name "Pixies".
    pixies: bool


class EngineUsage(BaseModel):
    """One engine's part of a period's tokens (B91)."""

    provider: str
    tokens: int
    sessions: int


class ProbeTotals(BaseModel):
    """The usage probes of a period: Nest overhead, not part of the other totals."""

    count: int = 0
    tokens: int = 0


class PeriodUsage(BaseModel):
    unit: PeriodUnit
    # The period's first and last local days.
    start: date
    end: date
    # Whether the period holds today.
    current: bool
    # Distinct chats with tokens recorded in the period.
    sessions: int
    # Chats and subagents together.
    tokens: TokenTotals
    # The subagents' part of `tokens`.
    subagents: TokenTotals
    bars: list[BarUsage]
    # By project, most tokens first; none without tokens.
    projects: list[ProjectUsage]
    probes: ProbeTotals = Field(default_factory=ProbeTotals)
    # The Claude calls artifact pages made (B88), Nest overhead like the probes.
    asks: ProbeTotals = Field(default_factory=ProbeTotals)
    # By engine, Claude first, then by name; none without tokens (B91).
    engines: list[EngineUsage] = Field(default_factory=list[EngineUsage])


class LimitWindow(BaseModel):
    utilization: float
    resets_at: datetime | None
    # When the engine last reported this window.
    updated_at: datetime


class UsageLimits(BaseModel):
    five_hour: LimitWindow | None
    seven_day: LimitWindow | None


class EngineLimitWindow(LimitWindow):
    """One of another engine's windows, by its length (B91)."""

    # None when the engine left the length out.
    minutes: int | None

    @computed_field
    @property
    def label(self) -> str:
        """ "5 hour", "Weekly", "30 day": what clients call the window."""
        return window_label(self.minutes)


class EngineLimits(BaseModel):
    """Another engine's windows, whichever its plan has, shortest first (B91: Codex)."""

    windows: list[EngineLimitWindow]


CLAUDE = "claude"
# The engines whose usage windows Nest keeps (B91).
type UsageProvider = Literal["claude", "codex"]
