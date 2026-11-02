"""Performance runs and daemon starts in the database (B115)."""

import json
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from pydantic import TypeAdapter

from nestd.clock import Clock
from nestd.perf.models import Collected, PerfRun
from nestd.storage.db import Database

RESTARTED = "Nest restarted"
# How many runs of each section Clear old runs keeps.
KEEP_PER_SECTION = 2

_RESULTS = TypeAdapter(dict[str, Collected])


@dataclass(frozen=True)
class Build:
    version: str
    git_commit: str | None


@dataclass(frozen=True)
class DaemonStart:
    started_at: datetime
    ready_ms: int


class PerfStore:
    def __init__(self, db: Database, clock: Clock) -> None:
        self._db = db
        self._clock = clock

    async def create(self, sections: Sequence[str], build: Build, machine: str) -> PerfRun:
        run = PerfRun(
            id=uuid4().hex,
            sections=list(sections),
            started_at=self._clock.now(),
            finished_at=None,
            state="running",
            error=None,
            version=build.version,
            git_commit=build.git_commit,
            machine=machine,
            results={},
        )
        await self._db.execute(
            "INSERT INTO perf_runs (id, sections, started_at, state, version, git_commit,"
            " machine) VALUES (?, ?, ?, 'running', ?, ?, ?)",
            (
                run.id,
                json.dumps(run.sections),
                run.started_at.isoformat(),
                build.version,
                build.git_commit,
                machine,
            ),
        )
        return run

    async def finish(self, run_id: str, results: dict[str, Collected]) -> None:
        await self._db.execute(
            "UPDATE perf_runs SET state = 'done', finished_at = ?, results = ? WHERE id = ?",
            (self._clock.now().isoformat(), _RESULTS.dump_json(results).decode(), run_id),
        )

    async def fail(self, run_id: str, error: str) -> None:
        await self._db.execute(
            "UPDATE perf_runs SET state = 'failed', finished_at = ?, error = ? WHERE id = ?",
            (self._clock.now().isoformat(), error, run_id),
        )

    async def fail_running(self) -> int:
        """At startup: a run the daemon was in the middle of failed; how many there were."""
        return await self._db.execute(
            "UPDATE perf_runs SET state = 'failed', finished_at = ?, error = ?"
            " WHERE state = 'running'",
            (self._clock.now().isoformat(), RESTARTED),
        )

    async def running(self) -> PerfRun | None:
        row = await self._db.fetch_one(
            "SELECT * FROM perf_runs WHERE state = 'running' ORDER BY started_at DESC LIMIT 1"
        )
        return None if row is None else _run(row)

    async def done(self) -> list[PerfRun]:
        """Every finished run, newest first."""
        rows = await self._db.fetch_all(
            "SELECT * FROM perf_runs WHERE state = 'done' ORDER BY finished_at DESC, rowid DESC"
        )
        return [_run(row) for row in rows]

    async def count(self) -> int:
        row = await self._db.fetch_one("SELECT COUNT(*) AS n FROM perf_runs")
        return 0 if row is None else row["n"]

    async def clear_old(self) -> int:
        """Keep, for each section, the two latest finished runs that measured it, and the
        run in progress; every other run goes. How many were deleted."""
        keep: set[str] = set()
        seen: dict[str, int] = {}
        for run in await self.done():
            for section, result in run.results.items():
                if result.error is None and seen.get(section, 0) < KEEP_PER_SECTION:
                    seen[section] = seen.get(section, 0) + 1
                    keep.add(run.id)
        placeholders = ", ".join("?" for _ in keep)
        where = "state != 'running'" + (f" AND id NOT IN ({placeholders})" if keep else "")
        return await self._db.execute(f"DELETE FROM perf_runs WHERE {where}", tuple(keep))  # noqa: S608

    async def record_start(self, ready_ms: int, build: Build) -> None:
        await self._db.execute(
            "INSERT INTO daemon_starts (started_at, ready_ms, version, git_commit)"
            " VALUES (?, ?, ?, ?)",
            (self._clock.now().isoformat(), ready_ms, build.version, build.git_commit),
        )

    async def latest_start(self) -> DaemonStart | None:
        row = await self._db.fetch_one(
            "SELECT started_at, ready_ms FROM daemon_starts ORDER BY id DESC LIMIT 1"
        )
        if row is None:
            return None
        return DaemonStart(datetime.fromisoformat(row["started_at"]), row["ready_ms"])

    async def starts_since(self, since: datetime) -> int:
        row = await self._db.fetch_one(
            "SELECT COUNT(*) AS n FROM daemon_starts WHERE started_at >= ?", (since.isoformat(),)
        )
        return 0 if row is None else row["n"]


def _run(row: sqlite3.Row) -> PerfRun:
    finished = row["finished_at"]
    return PerfRun(
        id=row["id"],
        sections=json.loads(row["sections"]),
        started_at=datetime.fromisoformat(row["started_at"]),
        finished_at=None if finished is None else datetime.fromisoformat(finished),
        state=row["state"],
        error=row["error"],
        version=row["version"],
        git_commit=row["git_commit"],
        machine=row["machine"],
        results=_RESULTS.validate_json(row["results"]),
    )
