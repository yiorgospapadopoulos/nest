"""Turn usage and the latest usage windows in SQLite.

Turn rows stay when their session is deleted: the tokens were spent all the same.
"""

from datetime import UTC, date, datetime, timedelta, tzinfo
from sqlite3 import Row

from harness.clock import Clock
from harness.providers.base import TokenUsage, UsageInfo
from harness.storage.db import Database
from harness.usage.models import LimitWindow, MonthUsage, ProbeTotals, Turn, UsageLimits
from harness.usage.month import COMPONENTS, summarize, total

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

    async def record_probe(self, tokens: TokenUsage) -> None:
        """Tokens a usage probe used; counted apart from the user's sessions (D031)."""
        columns = ", ".join(COMPONENTS)
        await self._db.execute(
            f"INSERT INTO probe_usage (ts, {columns})"  # noqa: S608
            f" VALUES (?, {', '.join('?' for _ in COMPONENTS)})",
            (self._clock.now().isoformat(), *(getattr(tokens, name) for name in COMPONENTS)),
        )

    async def month(self, year: int, month: int) -> MonthUsage:
        rows = await self._rows_of_month("turn_usage", year, month)
        turns = [
            Turn(day=self._day(row["ts"]), session_id=row["session_id"], tokens=_tokens(row))
            for row in rows
        ]
        probes = [
            total(_tokens(row))
            for row in await self._rows_of_month("probe_usage", year, month)
            if (day := self._day(row["ts"])).year == year and day.month == month
        ]
        return summarize(year, month, turns).model_copy(
            update={"probes": ProbeTotals(count=len(probes), tokens=sum(probes))}
        )

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

    async def limits_updated_at(self) -> datetime | None:
        """When the engine last reported any window; None before the first report."""
        rows = await self._db.fetch_all(
            "SELECT updated_at FROM usage_limits ORDER BY updated_at DESC LIMIT 1"
        )
        return datetime.fromisoformat(rows[0]["updated_at"]) if rows else None

    async def limits(self) -> UsageLimits:
        rows = await self._db.fetch_all("SELECT * FROM usage_limits")
        windows = {row["name"]: LimitWindow.model_validate(dict(row)) for row in rows}
        return UsageLimits(five_hour=windows.get("five_hour"), seven_day=windows.get("seven_day"))

    async def _rows_of_month(self, table: str, year: int, month: int) -> list[Row]:
        first = date(year, month, 1)
        following = (first + timedelta(days=31)).replace(day=1)
        return await self._db.fetch_all(
            f"SELECT * FROM {table} WHERE ts >= ? AND ts < ?",  # noqa: S608
            ((_utc(first) - _MARGIN).isoformat(), (_utc(following) + _MARGIN).isoformat()),
        )

    def _day(self, ts: str) -> date:
        return datetime.fromisoformat(ts).astimezone(self._zone).date()


def _tokens(row: Row) -> TokenUsage:
    return TokenUsage(**{name: row[name] for name in COMPONENTS})


def _utc(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=UTC)
