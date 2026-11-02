"""What several collectors share: windows of days, medians, and where the events of a
window start."""

import statistics
from collections.abc import Iterable
from datetime import datetime, timedelta

from nestd.clock import Clock
from nestd.storage.db import Database

_ENGINE_NAMES = {"claude": "Claude", "codex": "Codex"}


def since(clock: Clock, days: int) -> datetime:
    return clock.now() - timedelta(days=days)


def median(values: Iterable[float]) -> float | None:
    kept = list(values)
    return statistics.median(kept) if kept else None


def slowest(values: Iterable[float]) -> float | None:
    return max(values, default=None)


def ms_between(start: str, end: str) -> float:
    return (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds() * 1000


def engine_name(provider: str) -> str:
    return _ENGINE_NAMES.get(provider, provider.replace("-", " ").capitalize())


def engine_order(providers: Iterable[str]) -> list[str]:
    """Claude, then Codex, then the others by name."""
    known = list(_ENGINE_NAMES)
    return sorted(set(providers), key=lambda p: (known.index(p) if p in known else len(known), p))


async def first_event_since(db: Database, moment: datetime) -> int:
    """An id such that the events with `id >= it` are exactly those at or after `moment`,
    found by halving the id range (events are stored in time order), so a window never
    scans the whole table."""
    row = await db.fetch_one(
        "SELECT COALESCE(MIN(id), 1) AS low, COALESCE(MAX(id), 0) AS high FROM events"
    )
    if row is None:
        return 1
    low, high = int(row["low"]), int(row["high"]) + 1
    while low < high:
        middle = (low + high) // 2
        found = await db.fetch_one(
            "SELECT id, ts FROM events WHERE id >= ? ORDER BY id LIMIT 1", (middle,)
        )
        if found is None or datetime.fromisoformat(found["ts"]) >= moment:
            high = middle
        else:
            low = int(found["id"]) + 1
    return low
