"""Reliability (C12), over the last 30 days: turns that ended in an error or were cut off,
and how often the daemon started."""

from collections.abc import Awaitable, Callable
from datetime import datetime

from nestd.clock import Clock
from nestd.events import types
from nestd.perf.collectors.common import first_event_since, since
from nestd.perf.models import Collected, Measured
from nestd.sessions.models import SessionState
from nestd.storage.db import Database

DAYS = 30


class Reliability:
    def __init__(
        self, db: Database, clock: Clock, starts_since: Callable[[datetime], Awaitable[int]]
    ) -> None:
        self._db = db
        self._clock = clock
        self._starts_since = starts_since

    async def __call__(self) -> Collected:
        start = since(self._clock, DAYS)
        first = await first_event_since(self._db, start)
        row = await self._db.fetch_one(
            "SELECT"
            " SUM(type = ?) AS turns,"
            " SUM(type = ? AND json_extract(payload, '$.is_error') = 1) AS errored,"
            " SUM(type = ? AND json_extract(payload, '$.state') = ?) AS interrupted"
            " FROM events WHERE id >= ? AND type IN (?, ?)",
            (
                types.SESSION_RESULT,
                types.SESSION_RESULT,
                types.SESSION_STATE,
                SessionState.INTERRUPTED.value,
                first,
                types.SESSION_RESULT,
                types.SESSION_STATE,
            ),
        )
        turns = (row["turns"] if row else None) or 0
        errored = (row["errored"] if row else None) or 0
        interrupted = (row["interrupted"] if row else None) or 0
        return Collected(
            metrics=[
                Measured(
                    id="errored",
                    label="Turns that failed",
                    unit="count",
                    better="lower",
                    value=errored,
                    sub=f"of {turns} turns",
                ),
                Measured(
                    id="error_rate",
                    label="Failed share",
                    unit="percent",
                    better="lower",
                    value=errored / turns * 100 if turns else None,
                ),
                Measured(
                    id="interrupted",
                    label="Turns cut off",
                    unit="count",
                    better="lower",
                    value=interrupted,
                ),
                Measured(
                    id="starts",
                    label="Daemon starts",
                    unit="count",
                    better="lower",
                    value=await self._starts_since(start),
                ),
            ]
        )
