"""The log of what each pixie did through its harness tools (B41), newest first."""

from datetime import datetime

from harness.clock import Clock
from harness.pixies.models import PixieActivity
from harness.storage.db import Database

# Entries kept per pixie; older ones are dropped as new ones come.
KEEP = 200


class ActivityStore:
    def __init__(self, db: Database, clock: Clock) -> None:
        self._db = db
        self._clock = clock

    async def add(self, pixie_id: str, tool: str, session_id: str | None, summary: str) -> None:
        async with self._db.transaction() as tx:
            await tx.execute(
                "INSERT INTO pixie_activity (pixie_id, ts, tool, session_id, summary)"
                " VALUES (?, ?, ?, ?, ?)",
                (pixie_id, self._clock.now().isoformat(), tool, session_id, summary),
            )
            await tx.execute(
                "DELETE FROM pixie_activity WHERE pixie_id = ? AND id NOT IN"
                " (SELECT id FROM pixie_activity WHERE pixie_id = ? ORDER BY id DESC LIMIT ?)",
                (pixie_id, pixie_id, KEEP),
            )

    async def list(self, pixie_id: str) -> list[PixieActivity]:
        rows = await self._db.fetch_all(
            "SELECT id, ts, tool, session_id, summary FROM pixie_activity WHERE pixie_id = ?"
            " ORDER BY id DESC",
            (pixie_id,),
        )
        return [
            PixieActivity(
                id=row["id"],
                ts=datetime.fromisoformat(row["ts"]),
                tool=row["tool"],
                session_id=row["session_id"],
                summary=row["summary"],
            )
            for row in rows
        ]
