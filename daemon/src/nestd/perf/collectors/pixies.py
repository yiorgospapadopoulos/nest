"""Pixies (C10), over the last 30 days: the tokens of pixie chats and habit runs and their
share of all tokens, how late habits woke, how long calls took, and what failed."""

from nestd.clock import Clock
from nestd.perf.collectors.common import median, ms_between, since
from nestd.perf.models import Collected, Measured, Part
from nestd.storage.db import Database

DAYS = 30
_TOKENS = (
    "t.input_tokens + t.output_tokens + t.cache_creation_input_tokens + t.cache_read_input_tokens"
)
FAILED_HABITS = ("failed", "stalled", "timed_out")


class Pixies:
    def __init__(self, db: Database, clock: Clock) -> None:
        self._db = db
        self._clock = clock

    async def __call__(self) -> Collected:
        start = since(self._clock, DAYS).isoformat()
        rows = await self._db.fetch_all(
            f"SELECT s.pixie_id IS NOT NULL AS pixie, s.habit_run_id IS NOT NULL AS habit,"  # noqa: S608
            f" SUM({_TOKENS}) AS tokens FROM turn_usage t LEFT JOIN sessions s"
            " ON s.id = t.session_id WHERE t.ts >= ? GROUP BY pixie, habit",
            (start,),
        )
        all_tokens = sum(row["tokens"] or 0 for row in rows)
        chats = sum(row["tokens"] or 0 for row in rows if row["pixie"] and not row["habit"])
        habits = sum(row["tokens"] or 0 for row in rows if row["pixie"] and row["habit"])
        pixie_tokens = chats + habits

        runs = await self._db.fetch_all(
            "SELECT due_at, started_at, outcome FROM pixie_habit_runs"
            " WHERE COALESCE(started_at, due_at) >= ?",
            (start,),
        )
        wakes = [
            max(0.0, ms_between(r["due_at"], r["started_at"]))
            for r in runs
            if r["due_at"] is not None and r["started_at"] is not None
        ]
        failed_runs = sum(1 for r in runs if r["outcome"] in FAILED_HABITS)

        calls = [
            *await self._db.fetch_all(
                "SELECT state, started_at, finished_at FROM pixie_calls WHERE started_at >= ?",
                (start,),
            ),
            *await self._db.fetch_all(
                "SELECT state, started_at, finished_at FROM pixie_bridged_calls"
                " WHERE started_at >= ?",
                (start,),
            ),
        ]
        call_times = [
            ms_between(c["started_at"], c["finished_at"])
            for c in calls
            if c["state"] == "done" and c["finished_at"] is not None
        ]
        failed_calls = sum(1 for c in calls if c["state"] == "failed")
        return Collected(
            metrics=[
                Measured(
                    id="tokens",
                    label="Pixie tokens",
                    unit="tokens",
                    better="lower",
                    value=pixie_tokens,
                    # A called pixie's tokens are stored as the caller's subagent tokens.
                    sub="pixie chats and habit runs; calls count under Subagents",
                    parts=[
                        Part(label="Chats", value=chats),
                        Part(label="Habit runs", value=habits),
                    ],
                ),
                Measured(
                    id="share",
                    label="Share of all tokens",
                    unit="percent",
                    better="lower",
                    value=pixie_tokens / all_tokens * 100 if all_tokens else None,
                ),
                Measured(
                    id="wake_delay",
                    label="Habit wake delay",
                    unit="ms",
                    better="lower",
                    value=median(wakes),
                    sub=f"{len(wakes)} runs",
                ),
                Measured(
                    id="call_time",
                    label="Call time",
                    unit="ms",
                    better="lower",
                    value=median(call_times),
                    sub=f"{len(call_times)} calls",
                ),
                Measured(
                    id="failed",
                    label="Failed runs and calls",
                    unit="count",
                    better="lower",
                    value=failed_runs + failed_calls,
                    sub=f"{failed_runs} habit runs, {failed_calls} calls",
                ),
            ]
        )
