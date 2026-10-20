"""B94: which engine Nest first saw signed in, kept so new chats default to its model."""

import json
from datetime import timedelta
from pathlib import Path

from nestd.engine.sign_ins import SignInStore
from nestd.storage.db import Database
from nestd.storage.migrations import PACKAGED
from tests.fakes import FakeClock

MIGRATION = "0037_engine_sign_ins.sql"


def _before(directory: Path) -> Path:
    directory.mkdir()
    for entry in PACKAGED.iterdir():
        if entry.name.endswith(".sql") and entry.name < MIGRATION:
            (directory / entry.name).write_text(entry.read_text(encoding="utf-8"))
    return directory


async def _old_install(tmp_path: Path, claude_plan: str | None) -> Path:
    path = tmp_path / "nest.db"
    old = await Database.open(path, _before(tmp_path / "old"))
    account = {"display_name": None, "email": None, "plan": claude_plan, "organization": None}
    await old.execute(
        "INSERT INTO engine_info (name, data, updated_at) VALUES ('account', ?, ?)",
        (json.dumps(account), "2026-10-01T09:00:00+00:00"),
    )
    codex = account | {"plan": "ChatGPT Free"}
    await old.execute(
        "INSERT INTO engine_info (name, data, updated_at) VALUES ('codex_account', ?, ?)",
        (json.dumps(codex), "2026-09-01T09:00:00+00:00"),
    )
    for slug, model in (("a", "default"), ("b", "opus"), ("c", None)):
        await old.execute(
            "INSERT INTO pixies (id, slug, name, mascot, color, model, permission_mode,"
            " autonomy, project_access, skills, can_call, position, created_at, updated_at)"
            " VALUES (?, ?, 'P', 'moth', '#8B7CF6', ?, 'default', 'observe', 'edit', '[]',"
            " '[]', 0, 'x', 'x')",
            (slug, slug, model),
        )
    await old.close()
    return path


async def test_an_install_signed_in_to_claude_counts_claude_first(
    tmp_path: Path, clock: FakeClock
) -> None:
    db = await Database.open(await _old_install(tmp_path, "Claude Pro"))
    try:
        assert await SignInStore(db, clock).first() == "claude"
        rows = await db.fetch_all("SELECT slug, model FROM pixies ORDER BY slug")
    finally:
        await db.close()

    # A pixie set to its engine's default entry waits to be given the concrete model.
    assert [(row["slug"], row["model"]) for row in rows] == [
        ("a", None),
        ("b", "opus"),
        ("c", None),
    ]


async def test_an_install_without_a_claude_plan_has_no_first_engine_yet(
    tmp_path: Path, clock: FakeClock
) -> None:
    db = await Database.open(await _old_install(tmp_path, None))
    try:
        assert await SignInStore(db, clock).first() is None
    finally:
        await db.close()


async def test_the_first_engine_seen_signed_in_stays_first(
    tmp_path: Path, clock: FakeClock
) -> None:
    db = await Database.open(tmp_path / "nest.db")
    try:
        store = SignInStore(db, clock)
        assert await store.first() is None

        await store.record("codex")
        clock.advance(timedelta(minutes=1))
        await store.record("claude")
        clock.advance(timedelta(minutes=1))
        await store.record("codex")

        assert await store.first() == "codex"
        rows = await db.fetch_all("SELECT provider, first_seen_at FROM engine_sign_ins")
    finally:
        await db.close()

    seen = {row["provider"]: row["first_seen_at"] for row in rows}
    assert seen["codex"] < seen["claude"]
