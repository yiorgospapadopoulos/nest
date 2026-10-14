import sqlite3

import pytest

from harness.pixies.errors import DuplicateSlugError, TeamNotFoundError
from harness.pixies.team_store import TeamStore
from harness.storage.db import Database
from tests.fakes import FakeClock


async def test_create_list_update_and_delete(db: Database, clock: FakeClock) -> None:
    store = TeamStore(db, clock)
    qa = await store.create("QA", "qa")
    docs = await store.create("Docs", "docs")

    renamed = await store.update(qa.id, name="Testers")
    removed = await store.delete(docs.id)

    assert (qa.position, docs.position) == (0, 1)
    assert renamed.name == "Testers"
    assert removed == []
    assert [t.id for t in await store.list_teams()] == [qa.id]
    assert await store.handles() == {"qa"}
    with pytest.raises(TeamNotFoundError):
        await store.get(docs.id)


async def test_handles_are_unique(db: Database, clock: FakeClock) -> None:
    store = TeamStore(db, clock)
    await store.create("QA", "qa")
    docs = await store.create("Docs", "docs")

    with pytest.raises(DuplicateSlugError, match="@qa"):
        await store.create("Other", "qa")
    with pytest.raises(DuplicateSlugError, match="@qa"):
        await store.update(docs.id, handle="qa")


async def test_an_unknown_leader_is_not_a_handle_conflict(db: Database, clock: FakeClock) -> None:
    store = TeamStore(db, clock)
    team = await store.create("QA", "qa")

    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY") as raised:
        await store.update(team.id, leader_id="no-such-pixie")

    assert not isinstance(raised.value, DuplicateSlugError)
