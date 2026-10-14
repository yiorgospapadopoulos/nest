"""The latest status of every connector, kept across sessions and restarts.

Each agent run reports its servers when it starts, when most are still `pending`, and after
each turn, when they have settled. `pending` never replaces a status already known, so a new
run starting does not undo what earlier turns learned. A server another run does not load
(such as a project's own MCP server) keeps its last reported status.
"""

import sqlite3
from datetime import datetime

from pydantic import JsonValue

from nestd.clock import Clock
from nestd.connectors.models import Connector
from nestd.connectors.naming import GROUPS, display_name, group_of, manage_hint
from nestd.events import types
from nestd.events.bus import EventBus
from nestd.providers.base import McpServer
from nestd.storage.db import Database

PENDING = "pending"


class ConnectorRegistry:
    def __init__(self, db: Database, clock: Clock, bus: EventBus) -> None:
        self._db = db
        self._clock = clock
        self._bus = bus

    async def report(self, session_id: str, servers: list[McpServer]) -> None:
        """Record what a session's agent reported; announce the list when a status changed."""
        before = await self.list_connectors()
        now = self._clock.now().isoformat()
        async with self._db.transaction() as tx:
            for server in servers:
                await tx.execute(
                    "INSERT INTO connectors (name, status, error, source, last_seen_at)"
                    " VALUES (?, ?, ?, ?, ?) ON CONFLICT (name) DO UPDATE SET"
                    " status = CASE WHEN excluded.status = ? THEN status ELSE excluded.status END,"
                    " error = CASE WHEN excluded.status = ? THEN error ELSE excluded.error END,"
                    " source = excluded.source, last_seen_at = excluded.last_seen_at",
                    (server.name, server.status, server.error, session_id, now, PENDING, PENDING),
                )
        after = await self.list_connectors()
        if _statuses(after) != _statuses(before):
            connectors: list[JsonValue] = [c.model_dump(mode="json") for c in after]
            await self._bus.publish(types.CONNECTORS_UPDATED, {"connectors": connectors})

    async def list_connectors(self) -> list[Connector]:
        """claude.ai connectors, then plugin servers, then local ones; by name in each."""
        rows = await self._db.fetch_all("SELECT * FROM connectors")
        connectors = [_connector(row) for row in rows]
        return sorted(
            connectors, key=lambda c: (GROUPS.index(c.group), c.display_name.casefold(), c.name)
        )


def _statuses(connectors: list[Connector]) -> set[tuple[str, str, str | None]]:
    return {(c.name, c.status, c.error) for c in connectors}


def _connector(row: sqlite3.Row) -> Connector:
    name: str = row["name"]
    group = group_of(name)
    return Connector(
        name=name,
        display_name=display_name(name),
        group=group,
        status=row["status"],
        error=row["error"],
        manage_hint=manage_hint(group),
        source=row["source"],
        last_seen_at=datetime.fromisoformat(row["last_seen_at"]),
    )
