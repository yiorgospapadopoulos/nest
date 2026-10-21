"""Turn usage and the latest usage windows in SQLite.

Turn rows stay when their session is deleted: the tokens were spent all the same. Each row
keeps the engine its chat ran on, and each engine its own windows (B91), by account (B98).
"""

import json
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, timedelta, tzinfo
from sqlite3 import Row

from nestd.clock import Clock
from nestd.providers.base import BankedResets, TokenUsage, UsageInfo, UsageWindow, window_label
from nestd.storage.db import Database, Transaction
from nestd.usage.models import (
    CLAUDE,
    AccountWindow,
    EngineLimits,
    EngineLimitWindow,
    LimitWindow,
    PeriodUnit,
    PeriodUsage,
    Turn,
    UsageLimits,
    UsageProvider,
)
from nestd.usage.period import COMPONENTS, bar_walls, period_of, summarize, total

# Wide enough for any stored time format, so every row in the period is read.
_MARGIN = timedelta(days=1)
# The lengths of Claude's windows, which it names instead (B98).
_CLAUDE_MINUTES = {"five_hour": 300, "seven_day": 7 * 24 * 60}

# The account in use for an engine (B98).
type ActiveAccount = Callable[[str], str]
type LimitsListener = Callable[[str], Awaitable[None]]


def first_account(provider: str) -> str:
    """The id of the engine's first account, the user's own login (B98)."""
    return f"{provider}-main"


class UsageStore:
    def __init__(
        self,
        db: Database,
        clock: Clock,
        zone: tzinfo | None = None,
        active: ActiveAccount = first_account,
    ) -> None:
        """`zone` decides which calendar day a turn falls on; None is the system's zone.
        `active` names the account windows are read and kept for when none is named.
        """
        self._db = db
        self._clock = clock
        self._zone = zone
        self._active = active
        self._listeners: list[LimitsListener] = []

    def listen(self, listener: LimitsListener) -> None:
        """Hear the account whose windows changed, after each report is kept."""
        self._listeners.append(listener)

    async def record_turn(self, session_id: str, tokens: TokenUsage) -> None:
        columns = ", ".join(COMPONENTS)
        await self._db.execute(
            f"INSERT INTO turn_usage (session_id, repo, provider, ts, {columns})"  # noqa: S608
            f" SELECT id, repo, provider, ?, {', '.join('?' for _ in COMPONENTS)}"
            " FROM sessions WHERE id = ?",
            (
                self._clock.now().isoformat(),
                *(getattr(tokens, name) for name in COMPONENTS),
                session_id,
            ),
        )

    async def record_subagent(self, session_id: str, message_id: str, tokens: TokenUsage) -> None:
        """A subagent's API reply (B84). Its streamed messages repeat the id: the reply
        keeps its first time and the largest count of each component reported.
        """
        columns = ", ".join(COMPONENTS)
        larger = ", ".join(f"{name} = max({name}, excluded.{name})" for name in COMPONENTS)
        await self._db.execute(
            "INSERT INTO turn_usage"  # noqa: S608
            f" (session_id, repo, provider, ts, subagent, message_id, {columns})"
            f" SELECT id, repo, provider, ?, 1, ?, {', '.join('?' for _ in COMPONENTS)}"
            " FROM sessions WHERE id = ?"
            " ON CONFLICT (session_id, message_id) WHERE message_id IS NOT NULL"
            f" DO UPDATE SET {larger}",
            (
                self._clock.now().isoformat(),
                message_id,
                *(getattr(tokens, name) for name in COMPONENTS),
                session_id,
            ),
        )

    async def record_probe(self, tokens: TokenUsage) -> None:
        """Tokens a usage probe used; counted apart from the user's sessions (D031)."""
        await self._record_overhead("probe_usage", tokens)

    async def record_ask(self, tokens: TokenUsage) -> None:
        """Tokens an artifact page's ask used (B88); counted apart like the probes'."""
        await self._record_overhead("ask_usage", tokens)

    async def _record_overhead(self, table: str, tokens: TokenUsage) -> None:
        columns = ", ".join(COMPONENTS)
        await self._db.execute(
            f"INSERT INTO {table} (ts, {columns})"  # noqa: S608
            f" VALUES (?, {', '.join('?' for _ in COMPONENTS)})",
            (self._clock.now().isoformat(), *(getattr(tokens, name) for name in COMPONENTS)),
        )

    async def period(self, unit: PeriodUnit, day: date) -> PeriodUsage:
        """The day, week, month or year holding `day`, by the local calendar."""
        period = period_of(unit, day)
        edges = [self._aware(wall) for wall in bar_walls(period)]
        turns = [
            Turn(
                at=datetime.fromisoformat(row["ts"]),
                session_id=row["session_id"],
                repo=row["repo"],
                subagent=bool(row["subagent"]),
                tokens=_tokens(row),
                provider=row["provider"],
            )
            for row in await self._rows("turn_usage", edges[0], edges[-1])
        ]
        probes = await self._overhead("probe_usage", edges)
        asks = await self._overhead("ask_usage", edges)
        today = self._clock.now().astimezone(self._zone).date()
        return summarize(period, edges, turns, probes, asks, today)

    async def _overhead(self, table: str, edges: list[datetime]) -> list[int]:
        return [
            total(_tokens(row))
            for row in await self._rows(table, edges[0], edges[-1])
            if edges[0] <= datetime.fromisoformat(row["ts"]) < edges[-1]
        ]

    async def update_limits(self, info: UsageInfo, account_id: str | None = None) -> None:
        """Keep the latest report of each window the engine included, as that account's
        (None: the engine's active one). Windows by length (another engine's, B91) come
        whole and replace the account's.
        """
        account = account_id or self._active(info.provider)
        now = self._clock.now().isoformat()
        named = [(name, window, None) for name, window in _claude_windows(info)]
        sized = [(_sized_name(w.minutes), w, w.minutes) for w in info.windows]
        async with self._db.transaction() as tx:
            if sized:
                await tx.execute("DELETE FROM usage_limits WHERE account_id = ?", (account,))
            for name, window, minutes in named + sized:
                await tx.execute(
                    "INSERT INTO usage_limits"
                    " (account_id, provider, name, utilization, resets_at, updated_at, minutes)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT (account_id, name) DO UPDATE SET"
                    " utilization = excluded.utilization, resets_at = excluded.resets_at,"
                    " updated_at = excluded.updated_at",
                    (
                        account,
                        info.provider,
                        name,
                        window.utilization,
                        None if window.resets_at is None else window.resets_at.isoformat(),
                        now,
                        minutes,
                    ),
                )
            if info.banked is not None:
                await self._keep_banked(tx, account, info.banked, now)
        for listener in self._listeners:
            await listener(account)

    async def update_banked(self, account_id: str, banked: BankedResets) -> None:
        """A Codex account's banked resets, read without windows (B98)."""
        async with self._db.transaction() as tx:
            await self._keep_banked(tx, account_id, banked, self._clock.now().isoformat())
        for listener in self._listeners:
            await listener(account_id)

    async def banked(self, account_id: str) -> BankedResets | None:
        """The account's last known banked resets; None before Codex said."""
        row = await self._db.fetch_one(
            "SELECT available, credits FROM banked_resets WHERE account_id = ?", (account_id,)
        )
        if row is None:
            return None
        return BankedResets.model_validate(
            {"available": row["available"], "credits": json.loads(row["credits"] or "null")}
        )

    async def _keep_banked(
        self, tx: Transaction, account_id: str, banked: BankedResets, now: str
    ) -> None:
        """A count read without details keeps the details read before while the count
        stays the same.
        """
        details = (
            None
            if banked.credits is None
            else json.dumps([credit.model_dump(mode="json") for credit in banked.credits])
        )
        await tx.execute(
            "INSERT INTO banked_resets (account_id, available, credits, updated_at)"
            " VALUES (?, ?, ?, ?)"
            " ON CONFLICT (account_id) DO UPDATE SET available = excluded.available,"
            " credits = CASE WHEN excluded.credits IS NULL"
            " AND banked_resets.available = excluded.available"
            " THEN banked_resets.credits ELSE excluded.credits END,"
            " updated_at = excluded.updated_at",
            (account_id, banked.available, details, now),
        )

    async def limits_updated_at(
        self, provider: UsageProvider = CLAUDE, account_id: str | None = None
    ) -> datetime | None:
        """When the account (None: the active one) last had any window reported; None
        before the first report.
        """
        rows = await self._db.fetch_all(
            "SELECT updated_at FROM usage_limits WHERE account_id = ?"
            " ORDER BY updated_at DESC LIMIT 1",
            (account_id or self._active(provider),),
        )
        return datetime.fromisoformat(rows[0]["updated_at"]) if rows else None

    async def limits(self, account_id: str | None = None) -> UsageLimits:
        """Claude's windows, of the account (None: the active one)."""
        rows = await self._db.fetch_all(
            "SELECT name, utilization, resets_at, updated_at FROM usage_limits"
            " WHERE account_id = ?",
            (account_id or self._active(CLAUDE),),
        )
        windows = {row["name"]: LimitWindow.model_validate(dict(row)) for row in rows}
        return UsageLimits(five_hour=windows.get("five_hour"), seven_day=windows.get("seven_day"))

    async def engine_limits(
        self, provider: UsageProvider, account_id: str | None = None
    ) -> EngineLimits:
        """Another engine's windows by length, shortest first (B91), of the account (None:
        the active one).
        """
        rows = await self._db.fetch_all(
            "SELECT utilization, resets_at, updated_at, minutes FROM usage_limits"
            " WHERE account_id = ? ORDER BY minutes IS NULL, minutes",
            (account_id or self._active(provider),),
        )
        return EngineLimits(windows=[EngineLimitWindow.model_validate(dict(row)) for row in rows])

    async def windows(self, account_id: str) -> list[AccountWindow]:
        """The account's windows, shortest first, each labelled (B98). One whose reset
        time has passed reads as reset until the engine reports it again.
        """
        rows = await self._db.fetch_all(
            "SELECT name, utilization, resets_at, updated_at, minutes FROM usage_limits"
            " WHERE account_id = ?",
            (account_id,),
        )
        now = self._clock.now()
        windows = [_account_window(row, now) for row in rows]
        return sorted(windows, key=lambda w: (w.minutes is None, w.minutes or 0))

    async def forget(self, account_id: str) -> None:
        """Drop the windows of an account that was removed."""
        async with self._db.transaction() as tx:
            for table in ("usage_limits", "banked_resets"):
                await tx.execute(
                    f"DELETE FROM {table} WHERE account_id = ?",  # noqa: S608
                    (account_id,),
                )

    async def _rows(self, table: str, start: datetime, end: datetime) -> list[Row]:
        return await self._db.fetch_all(
            f"SELECT * FROM {table} WHERE ts >= ? AND ts < ?",  # noqa: S608
            (
                (start - _MARGIN).astimezone(UTC).isoformat(),
                (end + _MARGIN).astimezone(UTC).isoformat(),
            ),
        )

    def _aware(self, wall: datetime) -> datetime:
        # A naive time's astimezone() reads it in the system's zone, clock changes included.
        return wall.astimezone() if self._zone is None else wall.replace(tzinfo=self._zone)


def _claude_windows(info: UsageInfo) -> list[tuple[str, UsageWindow]]:
    pairs = (("five_hour", info.five_hour), ("seven_day", info.seven_day))
    return [(name, window) for name, window in pairs if window is not None]


def _account_window(row: Row, now: datetime) -> AccountWindow:
    minutes: int | None = row["minutes"]
    if minutes is None:
        minutes = _CLAUDE_MINUTES.get(row["name"])
    resets_at = None if row["resets_at"] is None else datetime.fromisoformat(row["resets_at"])
    reset = resets_at is not None and resets_at <= now
    return AccountWindow(
        label=window_label(minutes),
        minutes=minutes,
        utilization=0.0 if reset else row["utilization"],
        resets_at=None if reset else resets_at,
        updated_at=datetime.fromisoformat(row["updated_at"]),
        reset=reset,
    )


def _sized_name(minutes: int | None) -> str:
    """A window's key by its length; an engine reports one window of each."""
    return "unsized" if minutes is None else f"{minutes}m"


def _tokens(row: Row) -> TokenUsage:
    return TokenUsage(**{name: row[name] for name in COMPONENTS})
