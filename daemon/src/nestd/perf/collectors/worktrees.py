"""Worktrees (C16): for the worktree chats of the last 30 days, how long the worktree took
to set up after the chat was created, and how long until its first turn started."""

import json

from nestd.clock import Clock
from nestd.events import types
from nestd.perf.collectors.common import first_event_since, median, ms_between, since, slowest
from nestd.perf.models import Collected, Measured
from nestd.storage.db import Database

DAYS = 30


class Worktrees:
    def __init__(self, db: Database, clock: Clock) -> None:
        self._db = db
        self._clock = clock

    async def __call__(self) -> Collected:
        first = await first_event_since(self._db, since(self._clock, DAYS))
        rows = await self._db.fetch_all(
            "SELECT session_id, type, ts, CASE WHEN type = ? THEN payload END AS payload"
            " FROM events WHERE id >= ? AND session_id IS NOT NULL AND type IN (?, ?, ?)"
            " ORDER BY id",
            (
                types.SESSION_STATE,
                first,
                types.SESSION_CREATED,
                types.SESSION_WORKSPACE,
                types.SESSION_STATE,
            ),
        )
        created: dict[str, str] = {}
        ready: dict[str, str] = {}
        turned: dict[str, str] = {}
        for row in rows:
            session = row["session_id"]
            if row["type"] == types.SESSION_CREATED:
                created.setdefault(session, row["ts"])
            elif row["type"] == types.SESSION_WORKSPACE:
                ready.setdefault(session, row["ts"])
            elif session not in turned and json.loads(row["payload"]).get("turn_start"):
                turned[session] = row["ts"]
        worktree_chats = [s for s in ready if s in created]
        setups = [ms_between(created[s], ready[s]) for s in worktree_chats]
        starts = [ms_between(created[s], turned[s]) for s in worktree_chats if s in turned]
        count = len(worktree_chats)
        return Collected(
            metrics=[
                Measured(
                    id="setup_median",
                    label="Setup, typical",
                    unit="ms",
                    better="lower",
                    value=median(setups),
                    sub=f"{count} worktree {'chat' if count == 1 else 'chats'}",
                ),
                Measured(
                    id="setup_slowest",
                    label="Setup, slowest",
                    unit="ms",
                    better="lower",
                    value=slowest(setups),
                ),
                Measured(
                    id="first_turn_median",
                    label="To the first turn, typical",
                    unit="ms",
                    better="lower",
                    value=median(starts),
                ),
                Measured(
                    id="first_turn_slowest",
                    label="To the first turn, slowest",
                    unit="ms",
                    better="lower",
                    value=slowest(starts),
                ),
            ]
        )
