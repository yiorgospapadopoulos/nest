"""Token totals of a day, week, month or year, with a bar per hour, day or month."""

import calendar
from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from nestd.providers.base import TokenUsage
from nestd.sessions.models import PIXIE_REPO_PREFIX
from nestd.usage.models import (
    CLAUDE,
    BarUsage,
    EngineUsage,
    PeriodUnit,
    PeriodUsage,
    ProbeTotals,
    ProjectUsage,
    TokenTotals,
    Turn,
)

COMPONENTS = tuple(TokenUsage.model_fields)
PIXIES = "Pixies"


@dataclass(frozen=True)
class Period:
    unit: PeriodUnit
    start: date
    end: date


def total(tokens: TokenUsage) -> int:
    return sum(getattr(tokens, name) for name in COMPONENTS)


def period_of(unit: PeriodUnit, day: date) -> Period:
    """The period of `unit` that holds `day`; weeks start on Monday."""
    match unit:
        case "day":
            return Period(unit, day, day)
        case "week":
            monday = day - timedelta(days=day.weekday())
            return Period(unit, monday, monday + timedelta(days=6))
        case "month":
            last = calendar.monthrange(day.year, day.month)[1]
            return Period(unit, day.replace(day=1), day.replace(day=last))
        case _:
            return Period(unit, date(day.year, 1, 1), date(day.year, 12, 31))


def bar_walls(period: Period) -> list[datetime]:
    """The local wall time each bar starts at, then the period's end."""
    following = period.end + timedelta(days=1)
    if period.unit == "day":
        hours = [datetime.combine(period.start, time(hour)) for hour in range(24)]
        return [*hours, datetime.combine(following, time())]
    if period.unit == "year":
        year = period.start.year
        return [datetime(year, month, 1) for month in range(1, 13)] + [datetime(year + 1, 1, 1)]
    days = (following - period.start).days
    return [datetime.combine(period.start + timedelta(days=n), time()) for n in range(days + 1)]


def summarize(
    period: Period,
    edges: list[datetime],
    turns: list[Turn],
    probes: list[int],
    asks: list[int],
    today: date,
) -> PeriodUsage:
    """`edges` are the bars' aware starts and the period's end; rows outside are ignored."""
    turns = [turn for turn in turns if edges[0] <= turn.at < edges[-1]]
    bar_tokens = [0] * (len(edges) - 1)
    bar_sessions: list[set[str]] = [set() for _ in bar_tokens]
    projects: defaultdict[tuple[str, bool], int] = defaultdict(int)
    for turn in turns:
        index = bisect_right(edges, turn.at) - 1
        bar_tokens[index] += total(turn.tokens)
        bar_sessions[index].add(turn.session_id)
        pixies = turn.repo.startswith(PIXIE_REPO_PREFIX)
        projects[PIXIES if pixies else turn.repo, pixies] += total(turn.tokens)
    return PeriodUsage(
        unit=period.unit,
        start=period.start,
        end=period.end,
        current=period.start <= today <= period.end,
        sessions=len({turn.session_id for turn in turns}),
        tokens=_totals(turns),
        subagents=_totals([turn for turn in turns if turn.subagent]),
        bars=[
            BarUsage(start=start, tokens=tokens, sessions=len(sessions))
            for start, tokens, sessions in zip(edges, bar_tokens, bar_sessions, strict=False)
        ],
        projects=[
            ProjectUsage(name=name, tokens=tokens, pixies=pixies)
            for (name, pixies), tokens in sorted(projects.items(), key=lambda kv: (-kv[1], kv[0]))
            if tokens
        ],
        probes=ProbeTotals(count=len(probes), tokens=sum(probes)),
        asks=ProbeTotals(count=len(asks), tokens=sum(asks)),
        engines=_engines(turns),
    )


def _engines(turns: list[Turn]) -> list[EngineUsage]:
    tokens: defaultdict[str, int] = defaultdict(int)
    sessions: defaultdict[str, set[str]] = defaultdict(set)
    for turn in turns:
        tokens[turn.provider] += total(turn.tokens)
        sessions[turn.provider].add(turn.session_id)
    return [
        EngineUsage(provider=name, tokens=count, sessions=len(sessions[name]))
        for name, count in sorted(tokens.items(), key=lambda kv: (kv[0] != CLAUDE, kv[0]))
        if count
    ]


def _totals(turns: list[Turn]) -> TokenTotals:
    sums = {name: sum(getattr(turn.tokens, name) for turn in turns) for name in COMPONENTS}
    return TokenTotals(**sums, total=sum(sums.values()))
