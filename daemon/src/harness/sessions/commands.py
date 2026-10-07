"""The slash commands and agents agent runs reported, kept per session and per repo (D032).

A full report replaces the session's list; a names-only report adds the names it lacks.
The repo keeps the last list of any of its sessions, for chats that have not started yet.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from harness.clock import Clock
from harness.providers.base import AgentInfo, CommandCatalog, SlashCommand
from harness.storage.db import Database, Transaction

type Scope = Literal["session", "repo"]


class CommandList(BaseModel):
    # Where the list comes from: the session's own runs, its repo's latest run, or nowhere yet.
    source: Literal["session", "repo", "none"]
    commands: list[SlashCommand] = Field(default_factory=list[SlashCommand])
    agents: list[AgentInfo] = Field(default_factory=list[AgentInfo])
    updated_at: datetime | None = None


class CommandStore:
    def __init__(self, db: Database, clock: Clock) -> None:
        self._db = db
        self._clock = clock

    async def report(self, session_id: str, catalog: CommandCatalog) -> None:
        """Keep `catalog` for the session and its repo; nothing if the session is gone."""
        async with self._db.transaction() as tx:
            session = await tx.fetch_one("SELECT repo FROM sessions WHERE id = ?", (session_id,))
            if session is None:
                return
            if catalog.partial:
                known = await _catalog(tx, "session", session_id)
                if known is not None:
                    catalog = _completed(known, catalog)
            await self._save(tx, "session", session_id, catalog)
            await self._save(tx, "repo", session["repo"], catalog)

    async def for_session(self, session_id: str, repo: str) -> CommandList:
        """The session's own list, or else its repo's."""
        own = await self._list("session", session_id)
        return own if own.source != "none" else await self.for_repo(repo)

    async def for_repo(self, repo: str) -> CommandList:
        return await self._list("repo", repo)

    async def _list(self, scope: Scope, key: str) -> CommandList:
        row = await self._db.fetch_one(
            "SELECT catalog, updated_at FROM command_catalogs WHERE scope = ? AND key = ?",
            (scope, key),
        )
        if row is None:
            return CommandList(source="none")
        catalog = CommandCatalog.model_validate_json(row["catalog"])
        return CommandList(
            source=scope,
            commands=catalog.commands,
            agents=catalog.agents,
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    async def _save(self, tx: Transaction, scope: Scope, key: str, catalog: CommandCatalog) -> None:
        stored = catalog.model_copy(update={"partial": False}).model_dump_json()
        await tx.execute(
            "INSERT INTO command_catalogs (scope, key, catalog, updated_at) VALUES (?, ?, ?, ?)"
            " ON CONFLICT (scope, key) DO UPDATE SET catalog = excluded.catalog,"
            " updated_at = excluded.updated_at",
            (scope, key, stored, self._clock.now().isoformat()),
        )


async def _catalog(tx: Transaction, scope: Scope, key: str) -> CommandCatalog | None:
    row = await tx.fetch_one(
        "SELECT catalog FROM command_catalogs WHERE scope = ? AND key = ?", (scope, key)
    )
    return None if row is None else CommandCatalog.model_validate_json(row["catalog"])


def _completed(known: CommandCatalog, names: CommandCatalog) -> CommandCatalog:
    """The known list plus the names it lacks, sorted by name."""
    commands = {c.name: c for c in names.commands} | {c.name: c for c in known.commands}
    agents = {a.name: a for a in names.agents} | {a.name: a for a in known.agents}
    return CommandCatalog(
        commands=sorted(commands.values(), key=lambda c: (c.name.lower(), c.name)),
        agents=sorted(agents.values(), key=lambda a: (a.name.lower(), a.name)),
    )
