"""Turn usage and the latest usage windows in SQLite.

Turn rows stay when their session is deleted: the tokens were spent all the same.
"""

from datetime import UTC, date, datetime, timedelta, tzinfo

from harness.clock import Clock
from harness.providers.base import TokenUsage, UsageInfo
from harness.storage.db import Database
from harness.usage.models import LimitWindow, MonthUsage, Turn, UsageLimits
from harness.usage.month import COMPONENTS, summarize

# Wide enough for any UTC offset, so every turn on a local day of the month is read.
_MARGIN = timedelta(days=1)


class UsageStore:
    def __init__(self, db: Database, clock: Clock, zone: tzinfo | None = None) -> None:
        """`zone` decides which calendar day a turn falls on; None is the system's zone."""
        self._db = db
        self._clock = clock
        self._zone = zone

    async def record_turn(self, session_id: str, tokens: TokenUsage) -> None:
        columns = ", ".join(COMPONENTS)
        await self._db.execute(
            f"INSERT INTO turn_usage (session_id, repo, ts, {columns})"  # noqa: S608
            f" SELECT id, repo, ?, {', '.join('?' for _ in COMPONENTS)} FROM sessions WHERE id = ?",
            (
                self._clock.now().isoformat(),
                *(getattr(tokens, name) for name in COMPONENTS),
                session_id,
            ),
        )

    async def month(self, year: int, month: int) -> MonthUsage:
        first = date(year, month, 1)
        following = (first + timedelta(days=31)).replace(day=1)
        rows = await self._db.fetch_all(
            "SELECT * FROM turn_usage WHERE ts >= ? AND ts < ?",
            ((_utc(first) - _MARGIN).isoformat(), (_utc(following) + _MARGIN).isoformat()),
        )
        turns = [
            Turn(
                day=datetime.fromisoformat(row["ts"]).astimezone(self._zone).date(),
                session_id=row["session_id"],
                tokens=TokenUsage(**{name: row[name] for name in COMPONENTS}),
            )
            for row in rows
        ]
        return summarize(year, month, turns)

    async def update_limits(self, info: UsageInfo) -> None:
        """Keep the latest report of each window the engine included."""
        now = self._clock.now().isoformat()
        async with self._db.transaction() as tx:
            for name, window in (("five_hour", info.five_hour), ("seven_day", info.seven_day)):
                if window is None:
                    continue
                await tx.execute(
                    "INSERT INTO usage_limits (name, utilization, resets_at, updated_at)"
                    " VALUES (?, ?, ?, ?) ON CONFLICT (name) DO UPDATE SET"
                    " utilization = excluded.utilization, resets_at = excluded.resets_at,"
                    " updated_at = excluded.updated_at",
                    (
                        name,
                        window.utilization,
                        None if window.resets_at is None else window.resets_at.isoformat(),
                        now,
                    ),
                )

    async def limits(self) -> UsageLimits:
        rows = await self._db.fetch_all("SELECT * FROM usage_limits")
        windows = {row["name"]: LimitWindow.model_validate(dict(row)) for row in rows}
        return UsageLimits(five_hour=windows.get("five_hour"), seven_day=windows.get("seven_day"))


def _utc(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=UTC)
