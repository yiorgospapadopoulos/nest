"""Pixie rows in SQLite."""

import json
import sqlite3
from datetime import datetime
from uuid import uuid4

from harness.clock import Clock
from harness.pixies.errors import DuplicateSlugError, InvalidOrderError, PixieNotFoundError
from harness.pixies.models import Pixie, PixieSettings
from harness.storage.db import Database, Transaction

_JSON = ("projects", "skills", "can_call", "allowed_tools", "disallowed_tools")
# Every pixie column, and how many of its `action` reports are unread (B42).
_SELECT = (
    "SELECT pixies.*, (SELECT COUNT(*) FROM pixie_reports AS r WHERE r.pixie_id = pixies.id"
    " AND r.severity = 'action' AND r.read_at IS NULL) AS unread_action_reports FROM pixies"
)


class PixieStore:
    def __init__(self, db: Database, clock: Clock) -> None:
        self._db = db
        self._clock = clock

    async def create(self, settings: PixieSettings, slug: str) -> Pixie:
        async with self._db.transaction() as tx:
            row = await tx.fetch_one("SELECT COALESCE(MAX(position) + 1, 0) AS next FROM pixies")
            position = row["next"] if row is not None else 0
            return await self._insert(tx, settings, slug, position, None)

    async def create_after(
        self, settings: PixieSettings, slug: str, position: int, team_id: str | None
    ) -> tuple[Pixie, list[str]]:
        """A pixie right after the one at `position`: the later ones move down one place.
        Returns it and the ids of the pixies that moved.
        """
        now = _column("updated_at", self._clock.now())
        async with self._db.transaction() as tx:
            rows = await tx.fetch_all("SELECT id FROM pixies WHERE position > ?", (position,))
            await tx.execute(
                "UPDATE pixies SET position = position + 1, updated_at = ? WHERE position > ?",
                (now, position),
            )
            pixie = await self._insert(tx, settings, slug, position + 1, team_id)
        return pixie, [row["id"] for row in rows]

    async def _insert(
        self,
        tx: Transaction,
        settings: PixieSettings,
        slug: str,
        position: int,
        team_id: str | None,
    ) -> Pixie:
        now = self._clock.now()
        pixie = Pixie(
            **settings.model_dump(),
            id=uuid4().hex,
            slug=slug,
            position=position,
            team_id=team_id,
            chat_session_id=None,
            created_at=now,
            updated_at=now,
        )
        values = {
            name: _column(name, value)
            for name, value in pixie.model_dump(exclude={"unread_action_reports"}).items()
        }
        try:
            await tx.execute(
                f"INSERT INTO pixies ({', '.join(values)})"  # noqa: S608
                f" VALUES ({', '.join('?' for _ in values)})",
                tuple(values.values()),
            )
        except sqlite3.IntegrityError as error:
            _check_slug_conflict(error, slug)
            raise
        return pixie

    async def get(self, pixie_id: str) -> Pixie:
        row = await self._db.fetch_one(f"{_SELECT} WHERE id = ?", (pixie_id,))
        if row is None:
            msg = f"unknown pixie {pixie_id!r}"
            raise PixieNotFoundError(msg)
        return _pixie(row)

    async def name(self, pixie_id: str) -> str | None:
        """The pixie's name, or None when there is no such pixie."""
        row = await self._db.fetch_one("SELECT name FROM pixies WHERE id = ?", (pixie_id,))
        return None if row is None else str(row["name"])

    async def list_pixies(self) -> list[Pixie]:
        rows = await self._db.fetch_all(f"{_SELECT} ORDER BY position, rowid")
        return [_pixie(row) for row in rows]

    async def members(self, team_id: str) -> list[Pixie]:
        """The team's pixies, in pixie order."""
        rows = await self._db.fetch_all(
            f"{_SELECT} WHERE team_id = ? ORDER BY position, rowid", (team_id,)
        )
        return [_pixie(row) for row in rows]

    async def slugs(self) -> set[str]:
        return {row["slug"] for row in await self._db.fetch_all("SELECT slug FROM pixies")}

    async def update(self, pixie_id: str, **changes: object) -> Pixie:
        await self.get(pixie_id)
        changes["updated_at"] = self._clock.now()
        # Column names come from code, never from requests.
        assignments = ", ".join(f"{name} = ?" for name in changes)
        try:
            await self._db.execute(
                f"UPDATE pixies SET {assignments} WHERE id = ?",  # noqa: S608
                (*(_column(name, value) for name, value in changes.items()), pixie_id),
            )
        except sqlite3.IntegrityError as error:
            _check_slug_conflict(error, str(changes.get("slug")))
            raise
        return await self.get(pixie_id)

    async def reorder(self, ids: list[str]) -> list[str]:
        """Positions 0..n-1 in the order of `ids`, which names every pixie once; returns
        the ids whose position changed. Read and written in one transaction, so a pixie
        created meanwhile makes the order incomplete instead of sharing a position.
        """
        now = _column("updated_at", self._clock.now())
        async with self._db.transaction() as tx:
            rows = await tx.fetch_all("SELECT id, position FROM pixies")
            positions = {row["id"]: row["position"] for row in rows}
            if len(set(ids)) != len(ids) or set(ids) != positions.keys():
                msg = "the order must name every pixie exactly once"
                raise InvalidOrderError(msg)
            moved = [(pos, pid) for pos, pid in enumerate(ids) if positions[pid] != pos]
            for position, pid in moved:
                await tx.execute(
                    "UPDATE pixies SET position = ?, updated_at = ? WHERE id = ?",
                    (position, now, pid),
                )
        return [pid for _, pid in moved]

    async def chat_sessions(self, pixie_id: str) -> list[str]:
        """Every session of the pixie: its current chat and the ones a reset archived."""
        rows = await self._db.fetch_all(
            "SELECT id FROM sessions WHERE pixie_id = ? ORDER BY rowid", (pixie_id,)
        )
        return [row["id"] for row in rows]

    async def set_chat(self, pixie_id: str, session_id: str | None) -> Pixie:
        return await self.update(pixie_id, chat_session_id=session_id)

    async def delete(self, pixie_id: str) -> None:
        await self._db.execute("DELETE FROM pixies WHERE id = ?", (pixie_id,))


def _check_slug_conflict(error: sqlite3.IntegrityError, slug: str) -> None:
    # Other constraints, such as a chat session that does not exist, re-raise unchanged.
    if "pixies.slug" in str(error):
        msg = f"a pixie called @{slug} already exists"
        raise DuplicateSlugError(msg) from error


def _column(name: str, value: object) -> object:
    if name in _JSON:
        return None if value is None else json.dumps(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _pixie(row: sqlite3.Row) -> Pixie:
    data = dict(row)
    for name in _JSON:
        data[name] = None if data[name] is None else json.loads(data[name])
    data["hidden"] = bool(data["hidden"])
    return Pixie.model_validate(data)
