from dataclasses import dataclass
from datetime import date, datetime

from pydantic import BaseModel

from harness.providers.base import TokenUsage


@dataclass(frozen=True)
class Turn:
    """One recorded turn, on the local calendar day it ended."""

    day: date
    session_id: str
    tokens: TokenUsage


class TokenTotals(TokenUsage):
    # All four components together.
    total: int = 0


class DayUsage(BaseModel):
    date: date
    tokens: int
    sessions: int


class MonthUsage(BaseModel):
    year: int
    month: int
    # Distinct sessions with a turn this month.
    sessions: int
    tokens: TokenTotals
    # Every day of the month, in order.
    days: list[DayUsage]


class LimitWindow(BaseModel):
    utilization: float
    resets_at: datetime | None
    # When the engine last reported this window.
    updated_at: datetime


class UsageLimits(BaseModel):
    five_hour: LimitWindow | None
    seven_day: LimitWindow | None
