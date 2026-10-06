import sqlite3
from pathlib import Path

import pytest

from harness.storage.db import Database, DatabaseError
from harness.storage.migrations import load_migrations


def write_migrations(directory: Path, files: dict[str, str]) -> Path:
    directory.mkdir()
    for name, sql in files.items():
        (directory / name).write_text(sql, encoding="utf-8")
    return directory


def test_packaged_migrations_are_found_in_the_installed_package() -> None:
    migrations = load_migrations()

    assert [m.version for m in migrations] == list(range(1, len(migrations) + 1))
    assert migrations[0].name == "0001_init.sql"
    assert "CREATE TABLE events" in migrations[0].sql


async def test_open_applies_schema_and_pragmas(tmp_path: Path) -> None:
    db = await Database.open(tmp_path / "h.db")
    try:
        tables = {row["name"] for row in await db.fetch_all("SELECT name FROM sqlite_master")}
        version = await db.fetch_one("PRAGMA user_version")
        journal = await db.fetch_one("PRAGMA journal_mode")
        foreign_keys = await db.fetch_one("PRAGMA foreign_keys")
    finally:
        await db.close()

    assert {"events", "devices", "pairing_codes", "sessions", "attachments"} <= tables
    assert version is not None
    assert version[0] == len(load_migrations())
    assert journal is not None
    assert journal[0] == "wal"
    assert foreign_keys is not None
    assert foreign_keys[0] == 1


async def test_reopening_keeps_data_and_does_not_reapply(tmp_path: Path) -> None:
    path = tmp_path / "h.db"
    db = await Database.open(path)
    await db.execute(
        "INSERT INTO events (type, ts, payload) VALUES (?, ?, ?)", ("x", "2026-01-01", "{}")
    )
    await db.close()

    reopened = await Database.open(path)
    try:
        rows = await reopened.fetch_all("SELECT type FROM events")
    finally:
        await reopened.close()

    assert [row["type"] for row in rows] == ["x"]


async def test_only_one_local_device_is_allowed(tmp_path: Path) -> None:
    db = await Database.open(tmp_path / "h.db")
    insert = (
        "INSERT INTO devices (id, name, token_hash, is_local, created_at) VALUES (?, ?, ?, 1, ?)"
    )
    try:
        await db.execute(insert, ("a", "Mac", "h1", "t"))
        with pytest.raises(sqlite3.IntegrityError):
            await db.execute(insert, ("b", "Mac", "h2", "t"))
    finally:
        await db.close()


async def test_failed_migration_is_rolled_back(tmp_path: Path) -> None:
    migrations = write_migrations(
        tmp_path / "m",
        {
            "0001_a.sql": "CREATE TABLE a (x INTEGER);",
            "0002_b.sql": "CREATE TABLE b (x INTEGER);\nINSERT INTO missing VALUES (1);",
        },
    )

    with pytest.raises(sqlite3.OperationalError, match="missing"):
        await Database.open(tmp_path / "h.db", migrations)

    good = write_migrations(tmp_path / "good", {"0001_a.sql": "CREATE TABLE a (x INTEGER);"})
    db = await Database.open(tmp_path / "h.db", good)
    try:
        tables = {row["name"] for row in await db.fetch_all("SELECT name FROM sqlite_master")}
        version = await db.fetch_one("PRAGMA user_version")
    finally:
        await db.close()
    assert tables == {"a"}
    assert version is not None
    assert version[0] == 1


async def test_database_newer_than_code_is_refused(tmp_path: Path) -> None:
    two = write_migrations(tmp_path / "two", {"0001_a.sql": "SELECT 1;", "0002_b.sql": "SELECT 1;"})
    one = write_migrations(tmp_path / "one", {"0001_a.sql": "SELECT 1;"})
    await (await Database.open(tmp_path / "h.db", two)).close()

    with pytest.raises(DatabaseError, match="schema version 2 is newer than supported 1"):
        await Database.open(tmp_path / "h.db", one)


def test_migration_versions_must_be_contiguous(tmp_path: Path) -> None:
    directory = write_migrations(tmp_path / "m", {"0001_a.sql": "", "0003_c.sql": ""})

    with pytest.raises(DatabaseError, match="expected migration 0002"):
        load_migrations(directory)


def test_migration_names_must_follow_the_pattern(tmp_path: Path) -> None:
    directory = write_migrations(tmp_path / "m", {"init.sql": ""})

    with pytest.raises(DatabaseError, match=r"init\.sql"):
        load_migrations(directory)


def test_non_sql_files_are_ignored(tmp_path: Path) -> None:
    directory = write_migrations(tmp_path / "m", {"0001_a.sql": "SELECT 1;", "README": "x"})

    assert [m.name for m in load_migrations(directory)] == ["0001_a.sql"]


async def insert_then_fail(db: Database) -> None:
    async with db.transaction() as tx:
        await tx.execute("INSERT INTO events (type, ts, payload) VALUES ('x', 't', '{}')")
        raise RuntimeError


async def test_transaction_rolls_back_on_error(tmp_path: Path) -> None:
    db = await Database.open(tmp_path / "h.db")
    try:
        with pytest.raises(RuntimeError):
            await insert_then_fail(db)
        row = await db.fetch_one("SELECT COUNT(*) FROM events")
        missing = await db.fetch_one("SELECT * FROM events WHERE id = ?", (42,))
    finally:
        await db.close()

    assert row is not None
    assert row[0] == 0
    assert missing is None


async def test_execute_reports_affected_rows(tmp_path: Path) -> None:
    db = await Database.open(tmp_path / "h.db")
    try:
        await db.execute("INSERT INTO events (type, ts, payload) VALUES ('x', 't', '{}')")
        changed = await db.execute("UPDATE events SET type = 'y'")
        unchanged = await db.execute("UPDATE events SET type = 'z' WHERE id = 999")
    finally:
        await db.close()

    assert changed == 1
    assert unchanged == 0
