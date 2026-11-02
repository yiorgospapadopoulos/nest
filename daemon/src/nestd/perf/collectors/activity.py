"""Activity (C9): turns, chats and tokens a day over 14 and 90 days, and the turns of
each of the last 14 days. Neither more nor less is better."""

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, tzinfo

from nestd.clock import Clock
from nestd.perf.formatting import Unit
from nestd.perf.models import Collected, Measured, Point, Series
from nestd.storage.db import Database

SHORT_DAYS = 14
LONG_DAYS = 90


class Activity:
    def __init__(self, db: Database, clock: Clock, zone: tzinfo | None) -> None:
        """`zone` decides which day a turn falls on; None is the system's time zone."""
        self._db = db
        self._clock = clock
        self._zone = zone

    async def __call__(self) -> Collected:
        today = self._clock.now().astimezone(self._zone).date()
        first = today - timedelta(days=LONG_DAYS - 1)
        # A day early, so no turn of the first local day is missed; the dates filter below.
        rows = await self._db.fetch_all(
            "SELECT ts, session_id, subagent, input_tokens + output_tokens"
            " + cache_creation_input_tokens + cache_read_input_tokens AS tokens"
            " FROM turn_usage WHERE ts >= ?",
            ((self._clock.now() - timedelta(days=LONG_DAYS + 1)).isoformat(),),
        )
        turns: Counter[date] = Counter()
        tokens: Counter[date] = Counter()
        chats: defaultdict[date, set[str]] = defaultdict(set)
        for row in rows:
            day = datetime.fromisoformat(row["ts"]).astimezone(self._zone).date()
            if day < first or day > today:
                continue
            tokens[day] += row["tokens"]
            if not row["subagent"]:
                turns[day] += 1
                chats[day].add(row["session_id"])
        chat_counts = Counter({day: len(ids) for day, ids in chats.items()})

        def per_day(counts: Counter[date], days: int) -> float:
            start = today - timedelta(days=days - 1)
            return sum(n for day, n in counts.items() if day >= start) / days

        metrics: list[Measured] = []
        kinds: tuple[tuple[str, str, Unit, Counter[date]], ...] = (
            ("turns", "Turns a day", "count", turns),
            ("chats", "Chats a day", "count", chat_counts),
            ("tokens", "Tokens a day", "tokens", tokens),
        )
        for key, label, unit, counts in kinds:
            for days in (SHORT_DAYS, LONG_DAYS):
                metrics.append(
                    Measured(
                        id=f"{key}_{days}",
                        label=f"{label}, {days} days",
                        unit=unit,
                        better="none",
                        value=per_day(counts, days),
                    )
                )
        days = [today - timedelta(days=n) for n in range(SHORT_DAYS - 1, -1, -1)]
        return Collected(
            metrics=metrics,
            series=Series(
                label="Turns per day",
                points=[Point(day=day, value=turns[day]) for day in days],
            ),
        )
