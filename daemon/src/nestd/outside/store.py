"""Which outside clients are on, at what level (B151)."""

import sqlite3
from dataclasses import dataclass
from datetime import datetime

from nestd.clock import Clock
from nestd.outside.models import Access, ClientKind
from nestd.storage.db import Database


@dataclass(frozen=True)
class ClientRow:
    kind: ClientKind
    access: Access
    turned_on_at: datetime
    last_seen_at: datetime | None


class ClientStore:
    def __init__(self, db: Database, clock: Clock) -> None:
        self._db = db
        self._clock = clock

    async def get(self, kind: ClientKind) -> ClientRow | None:
        row = await self._db.fetch_one("SELECT * FROM outside_clients WHERE kind = ?", (kind,))
        return None if row is None else _row(row)

    async def list_on(self) -> list[ClientRow]:
        return [_row(row) for row in await self._db.fetch_all("SELECT * FROM outside_clients")]

    async def turn_on(self, kind: ClientKind, access: Access) -> None:
        """Switches the client on, or changes its level and keeps when it was turned on."""
        await self._db.execute(
            "INSERT INTO outside_clients (kind, access, turned_on_at) VALUES (?, ?, ?)"
            " ON CONFLICT (kind) DO UPDATE SET access = excluded.access",
            (kind, access, self._clock.now().isoformat()),
        )

    async def turn_off(self, kind: ClientKind) -> bool:
        return await self._db.execute("DELETE FROM outside_clients WHERE kind = ?", (kind,)) == 1

    async def seen(self, kind: ClientKind) -> None:
        await self._db.execute(
            "UPDATE outside_clients SET last_seen_at = ? WHERE kind = ?",
            (self._clock.now().isoformat(), kind),
        )


def _row(row: sqlite3.Row) -> ClientRow:
    seen = row["last_seen_at"]
    return ClientRow(
        kind=row["kind"],
        access=row["access"],
        turned_on_at=datetime.fromisoformat(row["turned_on_at"]),
        last_seen_at=None if seen is None else datetime.fromisoformat(seen),
    )
