"""What GitHub triggers have seen and done, in SQLite (B148): since when each one's events
count, and each event it took, once.

An owner is a habit (`habit:<id>`) or a project's chat trigger (`chat:<id>`).
"""

from collections.abc import Iterable
from datetime import datetime, timedelta

from nestd.clock import Clock
from nestd.storage.db import Database
from nestd.triggers.models import FireOutcome, GitHubEvent, TriggerActivity

KEEP = timedelta(days=7)


def habit_owner(habit_id: str) -> str:
    return f"habit:{habit_id}"


def chat_owner(trigger_id: str) -> str:
    return f"chat:{trigger_id}"


class TriggerStore:
    def __init__(self, db: Database, clock: Clock) -> None:
        self._db = db
        self._clock = clock

    async def since(self, owner: str, config: str) -> datetime:
        """Since when the owner's events count: now, the first time, or once its filters
        (`config`) changed.
        """
        row = await self._db.fetch_one(
            "SELECT config, since FROM trigger_watches WHERE owner = ?", (owner,)
        )
        if row is not None and row["config"] == config:
            return datetime.fromisoformat(row["since"])
        now = self._clock.now()
        await self._db.execute(
            "INSERT INTO trigger_watches (owner, config, since) VALUES (?, ?, ?)"
            " ON CONFLICT (owner) DO UPDATE SET config = excluded.config, since = excluded.since",
            (owner, config, now.isoformat()),
        )
        return now

    async def keep_only(self, owners: Iterable[str]) -> None:
        """Forget the watches of owners that are gone or watch nothing now, so one that
        comes back starts again from then.
        """
        kept = list(owners)
        marks = ", ".join("?" for _ in kept)
        await self._db.execute(
            f"DELETE FROM trigger_watches WHERE owner NOT IN ({marks})",  # noqa: S608
            tuple(kept),
        )

    async def claim(self, owner: str, event: GitHubEvent) -> bool:
        """True the first time the owner takes the event; it is recorded as queued."""
        changed = await self._db.execute(
            "INSERT OR IGNORE INTO trigger_events (owner, key, title, url, at, outcome)"
            " VALUES (?, ?, ?, ?, ?, 'queued')",
            (owner, event.key, event.title, event.url, self._clock.now().isoformat()),
        )
        return changed > 0

    async def settle(
        self,
        owner: str,
        key: str,
        outcome: FireOutcome,
        reason: str | None = None,
        session_id: str | None = None,
    ) -> None:
        await self._db.execute(
            "UPDATE trigger_events SET outcome = ?, reason = ?, session_id = ?"
            " WHERE owner = ? AND key = ?",
            (outcome, reason, session_id, owner, key),
        )

    async def started_since(self, owner: str, since: datetime) -> int:
        """How many chats the owner started since then."""
        row = await self._db.fetch_one(
            "SELECT COUNT(*) AS n FROM trigger_events"
            " WHERE owner = ? AND outcome = 'started' AND at >= ?",
            (owner, since.isoformat()),
        )
        return 0 if row is None else int(row["n"])

    async def last(self, trigger_ids: Iterable[str]) -> dict[str, TriggerActivity]:
        """The newest event each chat trigger took, by trigger id."""
        found: dict[str, TriggerActivity] = {}
        for trigger_id in trigger_ids:
            row = await self._db.fetch_one(
                "SELECT * FROM trigger_events WHERE owner = ? ORDER BY at DESC, rowid DESC LIMIT 1",
                (chat_owner(trigger_id),),
            )
            if row is not None:
                found[trigger_id] = TriggerActivity(
                    trigger_id=trigger_id,
                    outcome=row["outcome"],
                    reason=row["reason"],
                    at=datetime.fromisoformat(row["at"]),
                    title=row["title"],
                    url=row["url"],
                    session_id=row["session_id"],
                )
        return found

    async def prune(self) -> None:
        before = self._clock.now() - KEEP
        await self._db.execute("DELETE FROM trigger_events WHERE at < ?", (before.isoformat(),))
