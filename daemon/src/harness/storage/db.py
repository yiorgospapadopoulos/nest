"""Async SQLite access: one connection, serialized writes, explicit transactions."""

import asyncio
import sqlite3
from collections.abc import AsyncGenerator, Sequence
from contextlib import asynccontextmanager
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Self

import aiosqlite

from harness.storage.errors import DatabaseError
from harness.storage.migrations import PACKAGED, Migration, load_migrations

type Params = Sequence[object]


class Transaction:
    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    async def execute(self, sql: str, params: Params = ()) -> int:
        """Run a statement and return the number of affected rows."""
        async with self._conn.execute(sql, params) as cursor:
            return cursor.rowcount

    async def fetch_all(self, sql: str, params: Params = ()) -> list[sqlite3.Row]:
        async with self._conn.execute(sql, params) as cursor:
            return list(await cursor.fetchall())

    async def fetch_one(self, sql: str, params: Params = ()) -> sqlite3.Row | None:
        async with self._conn.execute(sql, params) as cursor:
            return await cursor.fetchone()


class Database:
    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn
        # Every statement goes through this lock so one coroutine's transaction is never
        # committed or rolled back by another coroutine sharing the connection.
        self._lock = asyncio.Lock()

    @classmethod
    async def open(cls, path: Path, migrations_dir: Traversable = PACKAGED) -> Self:
        migrations = load_migrations(migrations_dir)
        conn = await aiosqlite.connect(path)
        conn.row_factory = sqlite3.Row
        try:
            await conn.execute("PRAGMA journal_mode = WAL")
            await conn.execute("PRAGMA foreign_keys = ON")
            await _migrate(conn, migrations)
        except BaseException:
            await conn.close()
            raise
        return cls(conn)

    async def close(self) -> None:
        await self._conn.close()

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[Transaction]:
        async with self._lock:
            try:
                yield Transaction(self._conn)
            except BaseException:
                await self._conn.rollback()
                raise
            await self._conn.commit()

    async def execute(self, sql: str, params: Params = ()) -> int:
        async with self.transaction() as tx:
            return await tx.execute(sql, params)

    async def fetch_all(self, sql: str, params: Params = ()) -> list[sqlite3.Row]:
        async with self.transaction() as tx:
            return await tx.fetch_all(sql, params)

    async def fetch_one(self, sql: str, params: Params = ()) -> sqlite3.Row | None:
        async with self.transaction() as tx:
            return await tx.fetch_one(sql, params)


async def _migrate(conn: aiosqlite.Connection, migrations: list[Migration]) -> None:
    rows = list(await conn.execute_fetchall("PRAGMA user_version"))
    current: int = rows[0][0]
    if current > len(migrations):
        msg = f"database schema version {current} is newer than supported {len(migrations)}"
        raise DatabaseError(msg)
    for migration in migrations[current:]:
        script = f"BEGIN;\n{migration.sql}\nPRAGMA user_version = {migration.version};\nCOMMIT;"
        try:
            await conn.executescript(script)
        except BaseException:
            await conn.rollback()
            raise
