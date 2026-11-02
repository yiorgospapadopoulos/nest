"""Turn speed and cache (C6), from the stored events and token counts of the last 7 days:
how soon the first reply came, the typical and slowest turn, and how much of the input
the engines read from their cache; overall, and per engine when more than one ran."""

import json
from collections import defaultdict
from dataclasses import dataclass, field

from nestd.clock import Clock
from nestd.events import types
from nestd.perf.collectors.common import (
    engine_name,
    engine_order,
    first_event_since,
    median,
    ms_between,
    since,
    slowest,
)
from nestd.perf.models import Collected, Measured
from nestd.storage.db import Database

DAYS = 7


@dataclass
class _Turns:
    first_replies: list[float] = field(default_factory=list[float])
    durations: list[float] = field(default_factory=list[float])


@dataclass
class _Open:
    started: str
    replied: str | None = None


@dataclass(frozen=True)
class _Cache:
    read: int
    total: int

    @property
    def rate(self) -> float | None:
        return None if self.total == 0 else self.read / self.total * 100


class TurnSpeed:
    def __init__(self, db: Database, clock: Clock) -> None:
        self._db = db
        self._clock = clock

    async def __call__(self) -> Collected:
        turns = await self._turns()
        cache = await self._cache()
        everything = _Turns(
            [ms for t in turns.values() for ms in t.first_replies],
            [ms for t in turns.values() for ms in t.durations],
        )
        overall_read = sum(c.read for c in cache.values())
        overall = _Cache(overall_read, sum(c.total for c in cache.values()))
        metrics = [
            *_speed(everything, "", ""),
            Measured(
                id="cache_rate",
                label="Cache hit rate",
                unit="percent",
                better="higher",
                value=overall.rate,
            ),
        ]
        engines = engine_order([*turns, *cache])
        if len(engines) > 1:
            for provider in engines:
                name = engine_name(provider)
                metrics += _speed(turns.get(provider, _Turns()), f"_{provider}", f", {name}")[:2]
                rate = cache.get(provider)
                metrics.append(
                    Measured(
                        id=f"cache_rate_{provider}",
                        label=f"Cache hit rate, {name}",
                        unit="percent",
                        better="higher",
                        value=None if rate is None else rate.rate,
                    )
                )
        return Collected(metrics=metrics)

    async def _turns(self) -> dict[str, _Turns]:
        """Each finished turn's first reply and length, by engine. A turn starts with the
        `session.state` that marks `turn_start` and ends with the one that carries its
        `duration_ms`; its first reply is the first stored message in between."""
        first = await first_event_since(self._db, since(self._clock, DAYS))
        rows = await self._db.fetch_all(
            "SELECT e.session_id, e.type, e.ts, s.provider,"
            " CASE WHEN e.type = ? THEN e.payload END AS payload"
            " FROM events e JOIN sessions s ON s.id = e.session_id"
            " WHERE e.id >= ? AND e.type IN (?, ?) ORDER BY e.id",
            (types.SESSION_STATE, first, types.SESSION_STATE, types.SESSION_MESSAGE),
        )
        found: defaultdict[str, _Turns] = defaultdict(_Turns)
        open_turns: dict[str, _Open] = {}
        for row in rows:
            session = row["session_id"]
            if row["type"] == types.SESSION_MESSAGE:
                turn = open_turns.get(session)
                if turn is not None and turn.replied is None:
                    turn.replied = row["ts"]
                continue
            payload = json.loads(row["payload"])
            if payload.get("turn_start"):
                open_turns[session] = _Open(row["ts"])
                continue
            duration = payload.get("duration_ms")
            # Only the end carries the length; waiting for an approval does not end the turn.
            if not isinstance(duration, int):
                continue
            turn = open_turns.pop(session, None)
            if turn is None:
                continue
            stats = found[row["provider"]]
            stats.durations.append(float(duration))
            if turn.replied is not None:
                stats.first_replies.append(ms_between(turn.started, turn.replied))
        return dict(found)

    async def _cache(self) -> dict[str, _Cache]:
        rows = await self._db.fetch_all(
            "SELECT provider, SUM(cache_read_input_tokens) AS read,"
            " SUM(input_tokens + cache_creation_input_tokens + cache_read_input_tokens) AS total"
            " FROM turn_usage WHERE ts >= ? GROUP BY provider",
            (since(self._clock, DAYS).isoformat(),),
        )
        return {row["provider"]: _Cache(row["read"] or 0, row["total"] or 0) for row in rows}


def _speed(turns: _Turns, suffix: str, named: str) -> list[Measured]:
    count = len(turns.durations)
    return [
        Measured(
            id=f"first_reply{suffix}",
            label=f"First reply{named}",
            unit="ms",
            better="lower",
            value=median(turns.first_replies),
        ),
        Measured(
            id=f"typical{suffix}",
            label=f"Typical turn{named}",
            unit="ms",
            better="lower",
            value=median(turns.durations),
            sub=f"{count} {'turn' if count == 1 else 'turns'}",
        ),
        Measured(
            id=f"slowest{suffix}",
            label=f"Slowest turn{named}",
            unit="ms",
            better="lower",
            value=slowest(turns.durations),
        ),
    ]
