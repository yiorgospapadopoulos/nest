"""Pixie rows in SQLite."""

import json
import sqlite3
from datetime import datetime
from uuid import uuid4

from harness.clock import Clock
from harness.pixies.errors import DuplicateSlugError, PixieNotFoundError
from harness.pixies.models import Pixie, PixieSettings
from harness.storage.db import Database

_JSON = ("projects", "skills", "can_call", "allowed_tools", "disallowed_tools")


class PixieStore:
    def __init__(self, db: Database, clock: Clock) -> None:
        self._db = db
        self._clock = clock

    async def create(self, settings: PixieSettings, slug: str) -> Pixie:
        now = self._clock.now()
        row = await self._db.fetch_one("SELECT COALESCE(MAX(position) + 1, 0) AS next FROM pixies")
        pixie = Pixie(
            **settings.model_dump(),
            id=uuid4().hex,
            slug=slug,
            position=row["next"] if row is not None else 0,
            chat_session_id=None,
            created_at=now,
            updated_at=now,
        )
        values = {name: _column(name, value) for name, value in pixie.model_dump().items()}
        try:
            await self._db.execute(
                f"INSERT INTO pixies ({', '.join(values)})"  # noqa: S608
                f" VALUES ({', '.join('?' for _ in values)})",
                tuple(values.values()),
            )
        except sqlite3.IntegrityError as error:
            raise _taken(slug) from error
        return pixie

    async def get(self, pixie_id: str) -> Pixie:
        row = await self._db.fetch_one("SELECT * FROM pixies WHERE id = ?", (pixie_id,))
        if row is None:
            msg = f"unknown pixie {pixie_id!r}"
            raise PixieNotFoundError(msg)
        return _pixie(row)

    async def list_pixies(self) -> list[Pixie]:
        rows = await self._db.fetch_all("SELECT * FROM pixies ORDER BY position, rowid")
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
            raise _taken(str(changes.get("slug"))) from error
        return await self.get(pixie_id)

    async def set_chat(self, pixie_id: str, session_id: str | None) -> Pixie:
        return await self.update(pixie_id, chat_session_id=session_id)

    async def delete(self, pixie_id: str) -> None:
        await self._db.execute("DELETE FROM pixies WHERE id = ?", (pixie_id,))


def _taken(slug: str) -> DuplicateSlugError:
    return DuplicateSlugError(f"a pixie called @{slug} already exists")


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
