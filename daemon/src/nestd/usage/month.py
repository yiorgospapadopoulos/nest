"""Monthly token totals and per-day sums for the usage calendar."""

import calendar
from datetime import date

from nestd.providers.base import TokenUsage
from nestd.usage.models import DayUsage, MonthUsage, TokenTotals, Turn

COMPONENTS = tuple(TokenUsage.model_fields)


def total(tokens: TokenUsage) -> int:
    return sum(getattr(tokens, name) for name in COMPONENTS)


def summarize(year: int, month: int, turns: list[Turn]) -> MonthUsage:
    """Totals of the turns that fall in the month; turns outside it are ignored."""
    turns = [turn for turn in turns if (turn.day.year, turn.day.month) == (year, month)]
    sums = {name: sum(getattr(turn.tokens, name) for turn in turns) for name in COMPONENTS}
    days: list[DayUsage] = []
    for day_number in range(1, calendar.monthrange(year, month)[1] + 1):
        day = date(year, month, day_number)
        on_day = [turn for turn in turns if turn.day == day]
        days.append(
            DayUsage(
                date=day,
                tokens=sum(total(turn.tokens) for turn in on_day),
                sessions=len({turn.session_id for turn in on_day}),
            )
        )
    return MonthUsage(
        year=year,
        month=month,
        sessions=len({turn.session_id for turn in turns}),
        tokens=TokenTotals(**sums, total=sum(sums.values())),
        days=days,
    )
