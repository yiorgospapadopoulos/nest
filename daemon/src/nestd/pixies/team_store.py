"""Pixie team rows in SQLite (B40)."""

import sqlite3
from datetime import datetime
from uuid import uuid4

from nestd.clock import Clock
from nestd.pixies.errors import DuplicateSlugError, TeamNotFoundError
from nestd.pixies.models import PixieTeam
from nestd.storage.db import Database


class TeamStore:
    def __init__(self, db: Database, clock: Clock) -> None:
        self._db = db
        self._clock = clock

    async def create(self, name: str, handle: str) -> PixieTeam:
        now = self._clock.now()
        team_id = uuid4().hex
        try:
            async with self._db.transaction() as tx:
                row = await tx.fetch_one(
                    "SELECT COALESCE(MAX(position) + 1, 0) AS next FROM pixie_teams"
                )
                position = row["next"] if row is not None else 0
                await tx.execute(
                    "INSERT INTO pixie_teams (id, name, handle, leader_id, position,"
                    " created_at, updated_at) VALUES (?, ?, ?, NULL, ?, ?, ?)",
                    (team_id, name, handle, position, now.isoformat(), now.isoformat()),
                )
        except sqlite3.IntegrityError as error:
            # The id is new, so only the handle can clash.
            raise _taken(handle) from error
        return await self.get(team_id)

    async def get(self, team_id: str) -> PixieTeam:
        row = await self._db.fetch_one("SELECT * FROM pixie_teams WHERE id = ?", (team_id,))
        if row is None:
            msg = f"unknown team {team_id!r}"
            raise TeamNotFoundError(msg)
        return PixieTeam.model_validate(dict(row))

    async def list_teams(self) -> list[PixieTeam]:
        rows = await self._db.fetch_all("SELECT * FROM pixie_teams ORDER BY position, rowid")
        return [PixieTeam.model_validate(dict(row)) for row in rows]

    async def handles(self) -> set[str]:
        return {row["handle"] for row in await self._db.fetch_all("SELECT handle FROM pixie_teams")}

    async def update(self, team_id: str, **changes: object) -> PixieTeam:
        await self.get(team_id)
        changes["updated_at"] = self._clock.now()
        # Column names come from code, never from requests.
        assignments = ", ".join(f"{name} = ?" for name in changes)
        values = tuple(v.isoformat() if isinstance(v, datetime) else v for v in changes.values())
        try:
            await self._db.execute(
                f"UPDATE pixie_teams SET {assignments} WHERE id = ?",  # noqa: S608
                (*values, team_id),
            )
        except sqlite3.IntegrityError as error:
            _check_handle_conflict(error, str(changes.get("handle")))
            raise
        return await self.get(team_id)

    async def delete(self, team_id: str) -> list[str]:
        """Deletes the team; its pixies stay, without a team. Returns their ids."""
        now = self._clock.now().isoformat()
        async with self._db.transaction() as tx:
            if await tx.fetch_one("SELECT id FROM pixie_teams WHERE id = ?", (team_id,)) is None:
                msg = f"unknown team {team_id!r}"
                raise TeamNotFoundError(msg)
            rows = await tx.fetch_all(
                "SELECT id FROM pixies WHERE team_id = ? ORDER BY position, rowid", (team_id,)
            )
            await tx.execute(
                "UPDATE pixies SET team_id = NULL, updated_at = ? WHERE team_id = ?",
                (now, team_id),
            )
            await tx.execute("DELETE FROM pixie_teams WHERE id = ?", (team_id,))
        return [row["id"] for row in rows]


def _taken(handle: str) -> DuplicateSlugError:
    return DuplicateSlugError(f"a team called @{handle} already exists")


def _check_handle_conflict(error: sqlite3.IntegrityError, handle: str) -> None:
    # Other constraints, such as a leader that does not exist, re-raise unchanged.
    if "pixie_teams.handle" in str(error):
        raise _taken(handle) from error
