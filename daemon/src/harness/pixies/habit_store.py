"""Habit and habit run rows in SQLite (B42)."""

import json
import sqlite3
from datetime import datetime
from uuid import uuid4

from pydantic import BaseModel, Field, JsonValue

from harness.clock import Clock
from harness.errors import NotFoundError
from harness.pixies.habit_models import (
    CreateHabit,
    HabitRun,
    RunKind,
    RunOutcome,
    Schedule,
    Trigger,
)
from harness.storage.db import Database

# Finished runs kept per habit; queued and running ones are always kept.
KEEP_RUNS = 20
WAITING: tuple[RunOutcome, ...] = ("queued", "running")


class HabitNotFoundError(NotFoundError):
    pass


class StoredHabit(BaseModel):
    id: str
    pixie_id: str
    name: str
    prompt: str
    schedule: Schedule | None
    triggers: list[Trigger]
    max_minutes: int
    enabled: bool
    # Scheduled times up to here are handled.
    scheduled_through: datetime
    created_at: datetime
    updated_at: datetime


class StoredRun(HabitRun):
    """A run with what only the daemon needs: why it started, and its events."""

    kind: RunKind = Field(exclude=True)
    trigger_events: list[dict[str, JsonValue]] | None = Field(default=None, exclude=True)


class HabitStore:
    def __init__(self, db: Database, clock: Clock) -> None:
        self._db = db
        self._clock = clock

    # Habits

    async def create(self, pixie_id: str, habit: CreateHabit) -> StoredHabit:
        now = self._clock.now()
        stored = StoredHabit(
            **habit.model_dump(),
            id=uuid4().hex,
            pixie_id=pixie_id,
            scheduled_through=now,
            created_at=now,
            updated_at=now,
        )
        values = {name: _column(value) for name, value in stored.model_dump().items()}
        await self._db.execute(
            f"INSERT INTO pixie_habits ({', '.join(values)})"  # noqa: S608
            f" VALUES ({', '.join('?' for _ in values)})",
            tuple(values.values()),
        )
        return stored

    async def get(self, habit_id: str) -> StoredHabit:
        row = await self._db.fetch_one("SELECT * FROM pixie_habits WHERE id = ?", (habit_id,))
        if row is None:
            msg = f"unknown habit {habit_id!r}"
            raise HabitNotFoundError(msg)
        return _habit(row)

    async def of_pixie(self, pixie_id: str) -> list[StoredHabit]:
        rows = await self._db.fetch_all(
            "SELECT * FROM pixie_habits WHERE pixie_id = ? ORDER BY created_at, rowid",
            (pixie_id,),
        )
        return [_habit(row) for row in rows]

    async def enabled(self) -> list[StoredHabit]:
        rows = await self._db.fetch_all(
            "SELECT * FROM pixie_habits WHERE enabled = 1 ORDER BY created_at, rowid"
        )
        return [_habit(row) for row in rows]

    async def update(self, habit_id: str, **changes: object) -> StoredHabit:
        changes["updated_at"] = self._clock.now()
        # Column names come from code, never from requests.
        assignments = ", ".join(f"{name} = ?" for name in changes)
        await self._db.execute(
            f"UPDATE pixie_habits SET {assignments} WHERE id = ?",  # noqa: S608
            (*(_column(value) for value in changes.values()), habit_id),
        )
        return await self.get(habit_id)

    async def mark_scheduled(self, habit_id: str, through: datetime) -> None:
        """Scheduled times up to `through` are handled; the habit is not changed by it."""
        await self._db.execute(
            "UPDATE pixie_habits SET scheduled_through = ? WHERE id = ?",
            (through.isoformat(), habit_id),
        )

    async def delete(self, habit_id: str) -> None:
        """Deletes the habit and every run of it."""
        await self._db.execute("DELETE FROM pixie_habits WHERE id = ?", (habit_id,))

    # Runs

    async def add_run(
        self,
        habit: StoredHabit,
        kind: RunKind,
        due_at: datetime,
        trigger_events: list[dict[str, JsonValue]] | None = None,
    ) -> StoredRun:
        run = StoredRun(
            id=uuid4().hex,
            habit_id=habit.id,
            pixie_id=habit.pixie_id,
            kind=kind,
            session_id=None,
            due_at=due_at,
            started_at=None,
            ended_at=None,
            outcome="queued",
            reason=None,
            report_title=None,
            trigger_events=trigger_events,
        )
        values = {name: _column(getattr(run, name)) for name in StoredRun.model_fields}
        await self._db.execute(
            f"INSERT INTO pixie_habit_runs ({', '.join(values)})"  # noqa: S608
            f" VALUES ({', '.join('?' for _ in values)})",
            tuple(values.values()),
        )
        return run

    async def run(self, run_id: str) -> StoredRun | None:
        row = await self._db.fetch_one("SELECT * FROM pixie_habit_runs WHERE id = ?", (run_id,))
        return None if row is None else _run(row)

    async def update_run(self, run_id: str, **changes: object) -> StoredRun | None:
        """The run after the change; None when it is gone with its habit."""
        assignments = ", ".join(f"{name} = ?" for name in changes)
        await self._db.execute(
            f"UPDATE pixie_habit_runs SET {assignments} WHERE id = ?",  # noqa: S608
            (*(_column(value) for value in changes.values()), run_id),
        )
        return await self.run(run_id)

    async def set_report_title(self, run_id: str, title: str) -> None:
        """Keeps the first report's title."""
        await self._db.execute(
            "UPDATE pixie_habit_runs SET report_title = COALESCE(report_title, ?) WHERE id = ?",
            (title, run_id),
        )

    async def runs(self, habit_id: str) -> list[StoredRun]:
        """Newest first: the kept finished runs and any queued or running ones."""
        rows = await self._db.fetch_all(
            "SELECT * FROM pixie_habit_runs WHERE habit_id = ? ORDER BY rowid DESC", (habit_id,)
        )
        return [_run(row) for row in rows]

    async def last_run(self, habit_id: str) -> StoredRun | None:
        """The newest run that is not waiting in the queue."""
        row = await self._db.fetch_one(
            "SELECT * FROM pixie_habit_runs WHERE habit_id = ? AND outcome != 'queued'"
            " ORDER BY rowid DESC LIMIT 1",
            (habit_id,),
        )
        return None if row is None else _run(row)

    async def queued(self) -> list[StoredRun]:
        """Every queued run, the earliest due first."""
        rows = await self._db.fetch_all(
            "SELECT * FROM pixie_habit_runs WHERE outcome = 'queued' ORDER BY due_at, rowid"
        )
        return [_run(row) for row in rows]

    async def queued_of(self, habit_id: str, kind: RunKind) -> StoredRun | None:
        row = await self._db.fetch_one(
            "SELECT * FROM pixie_habit_runs WHERE habit_id = ? AND kind = ?"
            " AND outcome = 'queued' ORDER BY rowid LIMIT 1",
            (habit_id, kind),
        )
        return None if row is None else _run(row)

    async def last_triggered_at(self, habit_id: str) -> datetime | None:
        """When the habit's newest triggered run started, or was skipped."""
        row = await self._db.fetch_one(
            "SELECT COALESCE(started_at, ended_at) AS at FROM pixie_habit_runs"
            " WHERE habit_id = ? AND kind = 'trigger' AND outcome != 'queued'"
            " ORDER BY rowid DESC LIMIT 1",
            (habit_id,),
        )
        # Every run off the queue has started, or ended without starting.
        return None if row is None else datetime.fromisoformat(row["at"])

    async def set_trigger_events(self, run_id: str, events: list[dict[str, JsonValue]]) -> None:
        await self._db.execute(
            "UPDATE pixie_habit_runs SET trigger_events = ? WHERE id = ?",
            (json.dumps(events), run_id),
        )

    async def running(self) -> list[tuple[str, str]]:
        """The runs in progress, each with its session."""
        rows = await self._db.fetch_all(
            "SELECT id, session_id FROM pixie_habit_runs WHERE outcome = 'running'"
            " AND session_id IS NOT NULL ORDER BY rowid"
        )
        return [(row["id"], row["session_id"]) for row in rows]

    async def prune(self, habit_id: str) -> list[str]:
        """Drops the habit's finished runs beyond the newest KEEP_RUNS; returns the sessions
        of the dropped runs.
        """
        rows = await self._db.fetch_all(
            "DELETE FROM pixie_habit_runs WHERE habit_id = ? AND outcome NOT IN"
            " ('queued', 'running') AND id NOT IN (SELECT id FROM pixie_habit_runs"
            " WHERE habit_id = ? AND outcome NOT IN ('queued', 'running')"
            " ORDER BY rowid DESC LIMIT ?) RETURNING session_id",
            (habit_id, habit_id, KEEP_RUNS),
        )
        return [row["session_id"] for row in rows if row["session_id"] is not None]

    async def sessions_of(self, habit_id: str) -> list[str]:
        rows = await self._db.fetch_all(
            "SELECT session_id FROM pixie_habit_runs WHERE habit_id = ?"
            " AND session_id IS NOT NULL ORDER BY rowid",
            (habit_id,),
        )
        return [row["session_id"] for row in rows]


def _column(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, BaseModel):
        return value.model_dump_json()
    if isinstance(value, (list, dict)):
        return json.dumps(value)
    return value


def _habit(row: sqlite3.Row) -> StoredHabit:
    data = dict(row)
    data["schedule"] = None if data["schedule"] is None else json.loads(data["schedule"])
    data["triggers"] = json.loads(data["triggers"])
    data["enabled"] = bool(data["enabled"])
    return StoredHabit.model_validate(data)


def _run(row: sqlite3.Row) -> StoredRun:
    data = dict(row)
    events = data["trigger_events"]
    data["trigger_events"] = None if events is None else json.loads(events)
    return StoredRun.model_validate(data)
