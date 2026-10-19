"""Migration 0031 (B88): the artifact kinds widen to six and every version says who saved
it. SQLite cannot change a CHECK in place, so both tables are rebuilt; nothing else may
change: rows, indexes, the two triggers and the foreign key with its cascade.
"""

import sqlite3
from pathlib import Path

import pytest

from nestd.storage.db import Database
from nestd.storage.migrations import load_migrations

REBUILT = 31
_OBJECTS = (
    "SELECT type, name, tbl_name, sql FROM sqlite_master"
    " WHERE (tbl_name IN ('artifacts', 'artifact_versions') OR sql LIKE '%artifacts%')"
    " AND type IN ('index', 'trigger') ORDER BY type, name"
)


def migrations_until(directory: Path, last: int) -> Path:
    directory.mkdir()
    for migration in load_migrations()[:last]:
        (directory / migration.name).write_text(migration.sql, encoding="utf-8")
    return directory


async def before_the_rebuild(path: Path, tmp_path: Path) -> list[tuple[str, ...]]:
    """A database one migration short, with two artifacts; its indexes and triggers."""
    db = await Database.open(path, migrations_until(tmp_path / "older", REBUILT - 1))
    try:
        await db.execute(
            "INSERT INTO artifacts (id, title, kind, repo, session_id, chat_title, pixie_id,"
            " pixie_name, created_at, updated_at, seen_at) VALUES"
            " ('a1', 'Notes', 'markdown', 'web', 's1', 'Chat', NULL, NULL, 't1', 't2', 't3'),"
            " ('a2', 'Page', 'html', 'pixie:p1', 's2', NULL, 'p1', 'Boss', 't4', 't5', NULL)"
        )
        await db.execute(
            "INSERT INTO artifact_versions (artifact_id, version, title, size, created_at)"
            " VALUES ('a1', 1, 'Notes', 7, 't1'), ('a1', 2, 'Notes', 9, 't2'),"
            " ('a2', 1, 'Page', 11, 't4')"
        )
        return [tuple(row) for row in await db.fetch_all(_OBJECTS)]
    finally:
        await db.close()


async def test_the_rebuild_keeps_rows_indexes_triggers_and_the_foreign_key(
    tmp_path: Path,
) -> None:
    path = tmp_path / "nest.db"
    objects = await before_the_rebuild(path, tmp_path)

    db = await Database.open(path)
    try:
        artifacts = [tuple(row) for row in await db.fetch_all("SELECT * FROM artifacts")]
        versions = [
            tuple(row)
            for row in await db.fetch_all("SELECT * FROM artifact_versions ORDER BY rowid")
        ]
        after = [tuple(row) for row in await db.fetch_all(_OBJECTS)]
        broken = await db.fetch_all("PRAGMA foreign_key_check")
        foreign_keys = await db.fetch_one("PRAGMA foreign_keys")
        keys = await db.fetch_all("PRAGMA foreign_key_list(artifact_versions)")
        leftovers = await db.fetch_all("SELECT name FROM sqlite_master WHERE name LIKE '%_new'")
        await db.execute("DELETE FROM artifacts WHERE id = 'a1'")
        cascaded = await db.fetch_all("SELECT artifact_id, version FROM artifact_versions")
    finally:
        await db.close()

    assert artifacts == [
        ("a1", "Notes", "markdown", "web", "s1", "Chat", None, None, "t1", "t2", "t3"),
        ("a2", "Page", "html", "pixie:p1", "s2", None, "p1", "Boss", "t4", "t5", None),
    ]
    # Versions saved before were the agents'.
    assert versions == [
        ("a1", 1, "Notes", 7, "t1", "agent"),
        ("a1", 2, "Notes", 9, "t2", "agent"),
        ("a2", 1, "Page", 11, "t4", "agent"),
    ]
    assert after == objects
    assert {name for _, name, *_ in objects} >= {
        "artifacts_updated",
        "artifacts_session",
        "artifacts_pixie",
        "artifacts_keep_chat_title",
        "artifacts_keep_pixie_name",
    }
    assert broken == []
    assert foreign_keys is not None
    assert foreign_keys[0] == 1
    assert [(k["table"], k["from"], k["to"], k["on_delete"]) for k in keys] == [
        ("artifacts", "artifact_id", "id", "CASCADE")
    ]
    assert leftovers == []
    assert [tuple(row) for row in cascaded] == [("a2", 1)]


@pytest.mark.parametrize(
    "kind", ["markdown", "html", "slides", "document", "design", "design_system"]
)
async def test_the_six_kinds_are_allowed(tmp_path: Path, kind: str) -> None:
    db = await Database.open(tmp_path / "nest.db")
    try:
        await db.execute(
            "INSERT INTO artifacts (id, title, kind, repo, created_at, updated_at)"
            " VALUES ('a', 'T', ?, 'web', 't', 't')",
            (kind,),
        )
        await db.execute(
            "INSERT INTO artifact_versions (artifact_id, version, title, size, created_at,"
            " author) VALUES ('a', 1, 'T', 1, 't', 'user')"
        )
        row = await db.fetch_one("SELECT kind FROM artifacts")
    finally:
        await db.close()

    assert row is not None
    assert row["kind"] == kind


async def test_other_kinds_and_authors_are_refused(tmp_path: Path) -> None:
    db = await Database.open(tmp_path / "nest.db")
    try:
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
            await db.execute(
                "INSERT INTO artifacts (id, title, kind, repo, created_at, updated_at)"
                " VALUES ('a', 'T', 'pdf', 'web', 't', 't')"
            )
        await db.execute(
            "INSERT INTO artifacts (id, title, kind, repo, created_at, updated_at)"
            " VALUES ('a', 'T', 'document', 'web', 't', 't')"
        )
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
            await db.execute(
                "INSERT INTO artifact_versions (artifact_id, version, title, size, created_at,"
                " author) VALUES ('a', 1, 'T', 1, 't', 'bot')"
            )
        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
            await db.execute(
                "INSERT INTO artifact_versions (artifact_id, version, title, size, created_at)"
                " VALUES ('nope', 1, 'T', 1, 't')"
            )
    finally:
        await db.close()
