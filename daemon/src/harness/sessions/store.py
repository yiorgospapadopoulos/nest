"""Session rows in SQLite."""

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from harness.clock import Clock
from harness.sessions.errors import SessionNotFoundError
from harness.sessions.models import IN_FLIGHT, NewSession, Session, SessionState
from harness.storage.db import Database


class SessionStore:
    def __init__(self, db: Database, clock: Clock) -> None:
        self._db = db
        self._clock = clock

    async def create(self, new: NewSession) -> Session:
        now = self._clock.now()
        session = Session(
            **new.model_dump(),
            id=uuid4().hex,
            state=SessionState.STARTING,
            worktree_path=None,
            branch=None,
            provider_session_id=None,
            git_violation=False,
            created_at=now,
            updated_at=now,
            last_error=None,
        )
        values = {name: _column(value) for name, value in session.model_dump().items()}
        columns = ", ".join(values)
        placeholders = ", ".join("?" for _ in values)
        await self._db.execute(
            f"INSERT INTO sessions ({columns}) VALUES ({placeholders})",  # noqa: S608
            tuple(values.values()),
        )
        return session

    async def get(self, session_id: str) -> Session:
        row = await self._db.fetch_one("SELECT * FROM sessions WHERE id = ?", (session_id,))
        if row is None:
            msg = f"unknown session {session_id!r}"
            raise SessionNotFoundError(msg)
        return _session(row)

    async def list_sessions(self, repo: str | None = None, archived: bool = False) -> list[Session]:
        """Pinned first, then most recently updated; archived or not, optionally of one repo."""
        rows = await self._db.fetch_all(
            "SELECT * FROM sessions WHERE (? IS NULL OR repo = ?) AND (archived_at IS NOT NULL) = ?"
            " ORDER BY pinned DESC, updated_at DESC, rowid DESC",
            (repo, repo, archived),
        )
        return [_session(row) for row in rows]

    async def update(self, session_id: str, **changes: object) -> Session:
        changes["updated_at"] = self._clock.now()
        # Column names come from code, never from requests.
        assignments = ", ".join(f"{name} = ?" for name in changes)
        await self._db.execute(
            f"UPDATE sessions SET {assignments} WHERE id = ?",  # noqa: S608
            (*(_column(value) for value in changes.values()), session_id),
        )
        return await self.get(session_id)

    async def delete(self, session_id: str) -> None:
        """Delete the session with everything stored for it: approvals, attachments, events."""
        async with self._db.transaction() as tx:
            for table in ("approvals", "attachments", "events"):
                await tx.execute(f"DELETE FROM {table} WHERE session_id = ?", (session_id,))  # noqa: S608
            await tx.execute("DELETE FROM sessions WHERE id = ?", (session_id,))

    async def interrupt_in_flight(self) -> list[str]:
        """After a restart, turns that were in progress can only be resumed."""
        placeholders = ", ".join("?" for _ in IN_FLIGHT)
        rows = await self._db.fetch_all(
            f"UPDATE sessions SET state = ?, updated_at = ? WHERE state IN ({placeholders})"  # noqa: S608
            " RETURNING id",
            (SessionState.INTERRUPTED, self._clock.now().isoformat(), *IN_FLIGHT),
        )
        return [row["id"] for row in rows]


def _column(value: object) -> object:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, list):
        return json.dumps(value)
    return value


def _session(row: sqlite3.Row) -> Session:
    data = dict(row)
    data["allowed_tools"] = json.loads(data["allowed_tools"])
    return Session.model_validate(data)
