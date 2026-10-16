"""Pixie call rows in SQLite (B46)."""

import sqlite3
from datetime import datetime
from uuid import uuid4

from nestd.clock import Clock
from nestd.pixies.call_models import CallState, PixieCall
from nestd.storage.db import Database

# Newest first; calls started at the same moment by the order they were stored.
_NEWEST = "ORDER BY started_at DESC, rowid DESC"


class CallStore:
    def __init__(self, db: Database, clock: Clock) -> None:
        self._db = db
        self._clock = clock

    async def add(
        self,
        *,
        session_id: str,
        pixie_id: str,
        team_id: str | None,
        tool_use_id: str,
        fingerprint: str,
        background: bool,
        agent_id: str | None = None,
        continues: str | None = None,
    ) -> None:
        await self._db.execute(
            "INSERT INTO pixie_calls (id, session_id, pixie_id, team_id, tool_use_id, agent_id,"
            " continues, state, background, fingerprint, started_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, 'running', ?, ?, ?)",
            (
                uuid4().hex,
                session_id,
                pixie_id,
                team_id,
                tool_use_id,
                agent_id,
                continues,
                int(background),
                fingerprint,
                self._clock.now().isoformat(),
            ),
        )

    async def by_tool_use(self, session_id: str, tool_use_id: str) -> PixieCall | None:
        row = await self._db.fetch_one(
            "SELECT * FROM pixie_calls WHERE session_id = ? AND tool_use_id = ?",
            (session_id, tool_use_id),
        )
        return None if row is None else _call(row)

    async def by_agent(
        self, session_id: str, agent_id: str, running: bool = False
    ) -> PixieCall | None:
        """The latest call of the agent; with `running`, the latest still at work."""
        state = " AND state = 'running'" if running else ""
        row = await self._db.fetch_one(
            f"SELECT * FROM pixie_calls WHERE session_id = ? AND agent_id = ?{state} {_NEWEST}",  # noqa: S608
            (session_id, agent_id),
        )
        return None if row is None else _call(row)

    async def latest_agent(self, session_id: str, pixie_id: str) -> PixieCall | None:
        """The pixie's latest call in the chat whose agent can be continued."""
        row = await self._db.fetch_one(
            "SELECT * FROM pixie_calls WHERE session_id = ? AND pixie_id = ?"  # noqa: S608
            f" AND agent_id IS NOT NULL AND sent_away = 0 {_NEWEST}",
            (session_id, pixie_id),
        )
        return None if row is None else _call(row)

    async def update(self, call_id: str, **changes: object) -> None:
        # Column names come from code, never from requests.
        assignments = ", ".join(f"{name} = ?" for name in changes)
        values = tuple(v.isoformat() if isinstance(v, datetime) else v for v in changes.values())
        await self._db.execute(
            f"UPDATE pixie_calls SET {assignments} WHERE id = ?",  # noqa: S608
            (*values, call_id),
        )

    async def finish(self, call_id: str, state: CallState, **changes: object) -> None:
        await self.update(call_id, state=state, finished_at=self._clock.now(), **changes)

    async def in_group(self, session_id: str, pixie_id: str | None = None) -> list[PixieCall]:
        """The chat's calls not sent away, newest first; with `pixie_id`, only its."""
        pixie = "" if pixie_id is None else " AND pixie_id = ?"
        rows = await self._db.fetch_all(
            f"SELECT * FROM pixie_calls WHERE session_id = ? AND sent_away = 0{pixie} {_NEWEST}",  # noqa: S608
            (session_id,) if pixie_id is None else (session_id, pixie_id),
        )
        return [_call(row) for row in rows]

    async def chats_in_group(self) -> list[str]:
        """The chats with calls not sent away."""
        rows = await self._db.fetch_all(
            "SELECT DISTINCT session_id FROM pixie_calls WHERE sent_away = 0 ORDER BY session_id"
        )
        return [row["session_id"] for row in rows]

    async def send_away(self, session_id: str, pixie_ids: list[str], team_id: str | None) -> int:
        """Mark the calls of these pixies, and those made with the team, sent away (a
        null `team_id` matches no call)."""
        marks = ", ".join("?" for _ in pixie_ids)
        return await self._db.execute(
            "UPDATE pixie_calls SET sent_away = 1 WHERE session_id = ? AND sent_away = 0"  # noqa: S608
            f" AND (pixie_id IN ({marks}) OR team_id = ?)",
            (session_id, *pixie_ids, team_id),
        )

    async def interrupt(self, session_id: str, background: bool) -> int:
        """End the chat's running calls cut off with its turn; with `background`, also
        those that outlive a turn.
        """
        kept = "" if background else " AND background = 0"
        return await self._db.execute(
            "UPDATE pixie_calls SET state = 'interrupted', finished_at = ?"  # noqa: S608
            f" WHERE session_id = ? AND state = 'running'{kept}",
            (self._clock.now().isoformat(), session_id),
        )

    async def interrupt_all(self) -> list[str]:
        """End every running call; the chats they were in."""
        async with self._db.transaction() as tx:
            rows = await tx.fetch_all(
                "SELECT DISTINCT session_id FROM pixie_calls WHERE state = 'running'"
                " ORDER BY session_id"
            )
            await tx.execute(
                "UPDATE pixie_calls SET state = 'interrupted', finished_at = ?"
                " WHERE state = 'running'",
                (self._clock.now().isoformat(),),
            )
        return [row["session_id"] for row in rows]


def _call(row: sqlite3.Row) -> PixieCall:
    return PixieCall.model_validate(dict(row))
