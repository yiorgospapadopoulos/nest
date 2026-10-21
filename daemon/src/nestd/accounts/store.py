"""The engines' accounts and which one each engine uses, in SQLite (B98)."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from sqlite3 import Row

from nestd.clock import Clock
from nestd.errors import NotFoundError
from nestd.storage.db import Database

_COLUMNS = "id, provider, name, profile, position, created_at, email, plan, signed_in, checked_at"


@dataclass(frozen=True)
class StoredAccount:
    id: str
    provider: str
    # The user's own name for it, such as "Work".
    name: str | None
    # None for the first account, the user's own login.
    profile: Path | None
    position: int
    created_at: datetime
    # The engine's last answer about it.
    email: str | None
    plan: str | None
    signed_in: bool | None
    checked_at: datetime | None

    @property
    def first(self) -> bool:
        return self.profile is None


class AccountStore:
    def __init__(self, db: Database, clock: Clock) -> None:
        self._db = db
        self._clock = clock

    async def list(self) -> list[StoredAccount]:
        """Claude's first, then Codex's, each in the user's order."""
        rows = await self._db.fetch_all(
            f"SELECT {_COLUMNS} FROM engine_accounts"  # noqa: S608
            " ORDER BY provider != 'claude', provider, position, created_at"
        )
        return [_account(row) for row in rows]

    async def get(self, account_id: str) -> StoredAccount:
        row = await self._db.fetch_one(
            f"SELECT {_COLUMNS} FROM engine_accounts WHERE id = ?",  # noqa: S608
            (account_id,),
        )
        if row is None:
            msg = f"no account {account_id!r}"
            raise NotFoundError(msg)
        return _account(row)

    async def add(self, account_id: str, provider: str, profile: Path) -> StoredAccount:
        """A profile account, after the engine's others."""
        await self._db.execute(
            "INSERT INTO engine_accounts (id, provider, profile, position, created_at)"
            " SELECT ?, ?, ?, coalesce(max(position), -1) + 1, ?"
            " FROM engine_accounts WHERE provider = ?",
            (account_id, provider, str(profile), self._clock.now().isoformat(), provider),
        )
        return await self.get(account_id)

    async def rename(self, account_id: str, name: str | None) -> None:
        await self._db.execute(
            "UPDATE engine_accounts SET name = ? WHERE id = ?", (name, account_id)
        )

    async def record(
        self, account_id: str, signed_in: bool | None, email: str | None, plan: str | None
    ) -> None:
        """The engine's answer about the account; who it was stays known while signed out
        or when the engine could not be asked.
        """
        await self._db.execute(
            "UPDATE engine_accounts SET signed_in = ?, checked_at = ?,"
            " email = coalesce(?, email), plan = coalesce(?, plan) WHERE id = ?",
            (
                None if signed_in is None else int(signed_in),
                self._clock.now().isoformat(),
                email,
                plan,
                account_id,
            ),
        )

    async def delete(self, account_id: str) -> None:
        await self._db.execute("DELETE FROM engine_accounts WHERE id = ?", (account_id,))

    async def active(self) -> dict[str, str]:
        """The account each engine uses, by engine."""
        rows = await self._db.fetch_all("SELECT provider, account_id FROM active_accounts")
        return {row["provider"]: row["account_id"] for row in rows}

    async def set_active(self, provider: str, account_id: str) -> None:
        await self._db.execute(
            "INSERT INTO active_accounts (provider, account_id) VALUES (?, ?)"
            " ON CONFLICT (provider) DO UPDATE SET account_id = excluded.account_id",
            (provider, account_id),
        )


def _account(row: Row) -> StoredAccount:
    signed_in = row["signed_in"]
    checked_at = row["checked_at"]
    return StoredAccount(
        id=row["id"],
        provider=row["provider"],
        name=row["name"],
        profile=None if row["profile"] is None else Path(row["profile"]),
        position=row["position"],
        created_at=datetime.fromisoformat(row["created_at"]),
        email=row["email"],
        plan=row["plan"],
        signed_in=None if signed_in is None else bool(signed_in),
        checked_at=None if checked_at is None else datetime.fromisoformat(checked_at),
    )
