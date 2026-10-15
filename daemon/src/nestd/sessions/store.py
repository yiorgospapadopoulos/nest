"""Session rows in SQLite."""

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel

from nestd.clock import Clock
from nestd.prs.models import PrStatus
from nestd.sessions.errors import SessionNotFoundError
from nestd.sessions.models import IN_FLIGHT, NewSession, Session, SessionState
from nestd.storage.db import Database
from nestd.stuck.models import StuckFlag


class SessionStore:
    def __init__(self, db: Database, clock: Clock) -> None:
        self._db = db
        self._clock = clock

    async def create(self, new: NewSession, branch: str | None = None) -> Session:
        """`branch` is a worktree chat's branch name asked for before its worktree exists."""
        now = self._clock.now()
        session = Session(
            **new.model_dump(),
            id=uuid4().hex,
            state=SessionState.STARTING,
            worktree_path=None,
            branch=branch,
            provider_session_id=None,
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
        """Pinned first, then most recently updated; archived or not, optionally of one repo.
        Pixie chats are never listed here (D072).
        """
        rows = await self._db.fetch_all(
            "SELECT * FROM sessions WHERE (? IS NULL OR repo = ?) AND (archived_at IS NOT NULL) = ?"
            " AND pixie_id IS NULL ORDER BY pinned DESC, updated_at DESC, rowid DESC",
            (repo, repo, archived),
        )
        return [_session(row) for row in rows]

    async def provider_session_ids(self) -> set[str]:
        """The engine session ids of every session, archived and closed ones included, and
        those they had before their conversation was cleared.
        """
        rows = await self._db.fetch_all(
            "SELECT provider_session_id FROM sessions WHERE provider_session_id IS NOT NULL"
            " UNION SELECT provider_session_id FROM earlier_provider_sessions"
        )
        return {row["provider_session_id"] for row in rows}

    async def find_by_provider_session(self, provider_session_id: str) -> Session | None:
        row = await self._db.fetch_one(
            "SELECT * FROM sessions WHERE provider_session_id = ? OR id IN"
            " (SELECT session_id FROM earlier_provider_sessions WHERE provider_session_id = ?)"
            " ORDER BY rowid LIMIT 1",
            (provider_session_id, provider_session_id),
        )
        return None if row is None else _session(row)

    async def keep_earlier_provider_session(
        self, session_id: str, provider_session_id: str
    ) -> None:
        """The session's conversation was cleared and continues under a new engine id."""
        await self._db.execute(
            "INSERT OR IGNORE INTO earlier_provider_sessions (provider_session_id, session_id)"
            " VALUES (?, ?)",
            (provider_session_id, session_id),
        )

    async def update(self, session_id: str, **changes: object) -> Session:
        changes["updated_at"] = self._clock.now()
        # Column names come from code, never from requests.
        assignments = ", ".join(f"{name} = ?" for name in changes)
        await self._db.execute(
            f"UPDATE sessions SET {assignments} WHERE id = ?",  # noqa: S608
            (*(_column(value) for value in changes.values()), session_id),
        )
        return await self.get(session_id)

    async def set_pr(self, session_id: str, pr: PrStatus) -> Session:
        """Store the pull request's status without moving the session up the list."""
        await self._db.execute(
            "UPDATE sessions SET pr = ? WHERE id = ?", (pr.model_dump_json(), session_id)
        )
        return await self.get(session_id)

    async def set_stuck(self, session_id: str, flag: StuckFlag | None) -> Session:
        """Store why the session looks stuck (None: it does not) without reordering it."""
        await self._db.execute(
            "UPDATE sessions SET stuck = ? WHERE id = ?",
            (None if flag is None else flag.model_dump_json(), session_id),
        )
        return await self.get(session_id)

    async def clear_stuck(self) -> list[str]:
        """Clear every stuck flag, as after a restart; returns the sessions that had one."""
        rows = await self._db.fetch_all(
            "UPDATE sessions SET stuck = NULL WHERE stuck IS NOT NULL RETURNING id"
        )
        return [row["id"] for row in rows]

    async def with_prs(self, repo: str | None = None) -> list[Session]:
        """Sessions with a pull request, newest first, optionally of one repo."""
        rows = await self._db.fetch_all(
            "SELECT * FROM sessions WHERE pr_url IS NOT NULL AND (? IS NULL OR repo = ?)"
            " ORDER BY created_at DESC, rowid DESC",
            (repo, repo),
        )
        return [_session(row) for row in rows]

    async def started_by(self, pixie_id: str) -> list[Session]:
        """Every chat the pixie started with its tools, oldest first (B41)."""
        rows = await self._db.fetch_all(
            "SELECT * FROM sessions WHERE started_by_pixie = ? ORDER BY created_at, rowid",
            (pixie_id,),
        )
        return [_session(row) for row in rows]

    async def batch_members(self, pixie_id: str) -> list[Session]:
        """The pixie's started chats whose report has not gone back to it yet, oldest first."""
        rows = await self._db.fetch_all(
            "SELECT * FROM sessions WHERE started_by_pixie = ? AND pixie_batch IS NOT NULL"
            " ORDER BY created_at, rowid",
            (pixie_id,),
        )
        return [_session(row) for row in rows]

    async def batch_pixies(self) -> list[str]:
        """The pixies with started chats whose report has not gone back yet."""
        rows = await self._db.fetch_all(
            "SELECT DISTINCT started_by_pixie FROM sessions"
            " WHERE pixie_batch IS NOT NULL AND started_by_pixie IS NOT NULL"
            " ORDER BY started_by_pixie"
        )
        return [row["started_by_pixie"] for row in rows]

    async def clear_batch(self, session_ids: list[str]) -> None:
        """Their report went back: they leave their batch, without moving in the lists."""
        for session_id in session_ids:
            await self._db.execute(
                "UPDATE sessions SET pixie_batch = NULL WHERE id = ?", (session_id,)
            )

    async def delete(self, session_id: str) -> None:
        """Delete the session with everything stored for it: approvals, attachments, events,
        queued messages, earlier engine session ids and its command list.
        """
        async with self._db.transaction() as tx:
            for table in (
                *("approvals", "attachments", "checkpoints", "events", "queued_messages"),
                "earlier_provider_sessions",
            ):
                await tx.execute(f"DELETE FROM {table} WHERE session_id = ?", (session_id,))  # noqa: S608
            await tx.execute(
                "DELETE FROM command_catalogs WHERE scope = 'session' AND key = ?", (session_id,)
            )
            await tx.execute("DELETE FROM sessions WHERE id = ?", (session_id,))

    async def save_checkpoint(self, session_id: str, event_id: int, checkpoint_id: str) -> None:
        """The engine's id for the user message of event `event_id` (IMP-02)."""
        await self._db.execute(
            "INSERT OR REPLACE INTO checkpoints (event_id, session_id, checkpoint_id)"
            " VALUES (?, ?, ?)",
            (event_id, session_id, checkpoint_id),
        )

    async def checkpoint(self, session_id: str, event_id: int) -> str | None:
        """The checkpoint of the session's user message event `event_id`, if the engine
        reported one.
        """
        row = await self._db.fetch_one(
            "SELECT checkpoint_id FROM checkpoints WHERE session_id = ? AND event_id = ?",
            (session_id, event_id),
        )
        return None if row is None else row["checkpoint_id"]

    async def drop_events(self, session_id: str, first: int, last: int) -> None:
        """Forget the session's events `first` to `last`, with their checkpoints and search
        entries (a rewound conversation, B59).
        """
        async with self._db.transaction() as tx:
            for table, column in (("checkpoints", "event_id"), ("search_index", "event_id")):
                await tx.execute(
                    f"DELETE FROM {table} WHERE session_id = ? AND {column} BETWEEN ? AND ?",  # noqa: S608
                    (session_id, first, last),
                )
            await tx.execute(
                "DELETE FROM events WHERE session_id = ? AND id BETWEEN ? AND ?",
                (session_id, first, last),
            )

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
    if isinstance(value, BaseModel):
        return value.model_dump_json()
    return value


def _session(row: sqlite3.Row) -> Session:
    data = dict(row)
    data["allowed_tools"] = json.loads(data["allowed_tools"])
    for column in ("context", "pr", "stuck"):
        data[column] = None if data[column] is None else json.loads(data[column])
    return Session.model_validate(data)
