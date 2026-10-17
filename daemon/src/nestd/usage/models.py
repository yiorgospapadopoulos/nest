from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from nestd.providers.base import TokenUsage

type PeriodUnit = Literal["day", "week", "month", "year"]


@dataclass(frozen=True)
class Turn:
    """One recorded row: a main-chat turn, or a subagent's API reply."""

    at: datetime
    session_id: str
    repo: str
    subagent: bool
    tokens: TokenUsage


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


class LimitWindow(BaseModel):
    utilization: float
    resets_at: datetime | None
    # When the engine last reported this window.
    updated_at: datetime


class UsageLimits(BaseModel):
    five_hour: LimitWindow | None
    seven_day: LimitWindow | None
