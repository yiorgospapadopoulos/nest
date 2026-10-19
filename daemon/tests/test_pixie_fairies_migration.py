"""B89: the fairy redesign renames every stored mascot."""

import json
from pathlib import Path

from nestd.storage.db import Database
from nestd.storage.migrations import PACKAGED

RENAMED = {
    "invader": "frost",
    "ghost": "brook",
    "cat": "bluebell",
    "owl": "moth",
    "robot": "star",
    "frog": "dragonfly",
    "mushroom": "rose",
    "bunny": "nightshade",
    "crab": "firefly",
    "sprout": "sprig",
}
MIGRATION = "0030_pixie_fairies.sql"


def _before_fairies(directory: Path) -> Path:
    """The packaged migrations up to the one under test."""
    directory.mkdir()
    for entry in PACKAGED.iterdir():
        if entry.name.endswith(".sql") and entry.name < MIGRATION:
            (directory / entry.name).write_text(entry.read_text(encoding="utf-8"))
    return directory


def _pixie_event(pixie_id: str, mascot: str) -> str:
    return json.dumps({"pixie": {"id": pixie_id, "name": "P", "mascot": mascot}})


async def test_every_old_mascot_is_renamed(tmp_path: Path) -> None:
    path = tmp_path / "nest.db"
    old = await Database.open(path, _before_fairies(tmp_path / "old"))
    for position, mascot in enumerate(RENAMED):
        await old.execute(
            "INSERT INTO pixies (id, slug, name, mascot, color, permission_mode, autonomy,"
            " project_access, skills, can_call, position, created_at, updated_at)"
            " VALUES (?, ?, 'P', ?, '#8B7CF6', 'default', 'observe', 'edit', '[]', '[]', ?,"
            " 'x', 'x')",
            (mascot, mascot, mascot, position),
        )
        await old.execute(
            "INSERT INTO events (type, ts, payload) VALUES ('pixie.updated', 'x', ?)",
            (_pixie_event(mascot, mascot),),
        )
    await old.execute(
        "INSERT INTO events (type, ts, payload) VALUES ('pixie.deleted', 'x', ?)",
        (json.dumps({"pixie_id": "cat"}),),
    )
    await old.close()

    db = await Database.open(path)
    try:
        pixies = await db.fetch_all("SELECT id, mascot FROM pixies")
        events = await db.fetch_all("SELECT type, payload FROM events ORDER BY id")
    finally:
        await db.close()

    assert {row["id"]: row["mascot"] for row in pixies} == RENAMED
    updated = [json.loads(row["payload"]) for row in events if row["type"] == "pixie.updated"]
    assert [event["pixie"]["mascot"] for event in updated] == list(RENAMED.values())
    assert updated[0] == {"pixie": {"id": "invader", "name": "P", "mascot": "frost"}}
    assert json.loads(events[-1]["payload"]) == {"pixie_id": "cat"}
