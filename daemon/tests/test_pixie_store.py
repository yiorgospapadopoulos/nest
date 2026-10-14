import sqlite3

import pytest

from harness.pixies.errors import DuplicateSlugError, InvalidOrderError, PixieNotFoundError
from harness.pixies.models import PixieSettings
from harness.pixies.store import PixieStore
from harness.storage.db import Database
from tests.fakes import FakeClock


async def test_create_list_update_and_delete(db: Database, clock: FakeClock) -> None:
    store = PixieStore(db, clock)
    first = await store.create(PixieSettings(name="Tester", projects=["repo"]), "tester")
    second = await store.create(PixieSettings(name="Reviewer", skills=["review"]), "reviewer")

    renamed = await store.update(first.id, name="QA", hidden=True)
    listed = await store.list_pixies()
    await store.delete(second.id)

    assert (first.position, second.position) == (0, 1)
    assert first.mascot == "invader"
    assert first.autonomy == "observe"
    assert first.project_access == "edit"
    assert first.allowed_tools == []
    assert first.projects == ["repo"]
    assert second.projects is None
    assert second.skills == ["review"]
    assert renamed.name == "QA"
    assert renamed.hidden is True
    assert [p.slug for p in listed] == ["tester", "reviewer"]
    assert await store.slugs() == {"tester"}
    with pytest.raises(PixieNotFoundError):
        await store.get(second.id)


async def test_a_taken_slug_is_a_conflict(db: Database, clock: FakeClock) -> None:
    store = PixieStore(db, clock)
    first = await store.create(PixieSettings(name="Tester"), "tester")
    other = await store.create(PixieSettings(name="Other"), "other")

    with pytest.raises(DuplicateSlugError):
        await store.create(PixieSettings(name="Tester"), "tester")
    with pytest.raises(DuplicateSlugError):
        await store.update(other.id, slug=first.slug)


async def test_missing_pixies(db: Database, clock: FakeClock) -> None:
    store = PixieStore(db, clock)

    with pytest.raises(PixieNotFoundError):
        await store.update("nope", name="x")
    with pytest.raises(PixieNotFoundError):
        await store.set_chat("nope", None)


async def test_an_unknown_chat_session_is_not_a_slug_conflict(
    db: Database, clock: FakeClock
) -> None:
    store = PixieStore(db, clock)
    pixie = await store.create(PixieSettings(name="Tester"), "tester")

    with pytest.raises(sqlite3.IntegrityError) as raised:
        await store.set_chat(pixie.id, "no-such-session")

    assert not isinstance(raised.value, DuplicateSlugError)
    assert "pixies.slug" not in str(raised.value)


async def test_create_re_raises_other_integrity_errors(db: Database, clock: FakeClock) -> None:
    store = PixieStore(db, clock)

    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY") as raised:
        await store.create_after(PixieSettings(name="Tester"), "tester", 0, "no-such-team")

    assert not isinstance(raised.value, DuplicateSlugError)
    assert await store.list_pixies() == []


async def test_create_after_moves_the_later_pixies_down(db: Database, clock: FakeClock) -> None:
    store = PixieStore(db, clock)
    a, b, c = [await store.create(PixieSettings(name=n), n.lower()) for n in ("A", "B", "C")]

    copy, moved = await store.create_after(PixieSettings(name="A 2"), "a-2", a.position, None)
    last, none_moved = await store.create_after(PixieSettings(name="Z"), "z", 3, None)

    assert copy.position == 1
    assert moved == [b.id, c.id]
    assert (last.position, none_moved) == (4, [])
    assert [p.id for p in await store.list_pixies()] == [a.id, copy.id, b.id, c.id, last.id]


async def test_chat_sessions_lists_the_current_and_the_archived_chats(
    db: Database, clock: FakeClock
) -> None:
    store = PixieStore(db, clock)
    pixie = await store.create(PixieSettings(name="Tester"), "tester")
    other = await store.create(PixieSettings(name="Other"), "other")
    for session_id, owner in (("s1", pixie.id), ("s2", pixie.id), ("s3", other.id)):
        await db.execute(
            "INSERT INTO sessions (id, repo, title, prompt, mode, state, permission_mode, provider,"
            " pixie_id, created_at, updated_at)"
            " VALUES (?, ?, 't', 'p', 'in_place', 'idle', 'default', 'claude', ?, 'x', 'x')",
            (session_id, f"pixie:{owner}", owner),
        )

    assert await store.chat_sessions(pixie.id) == ["s1", "s2"]
    assert await store.chat_sessions("nope") == []


async def test_name_is_none_for_a_missing_pixie(db: Database, clock: FakeClock) -> None:
    store = PixieStore(db, clock)
    pixie = await store.create(PixieSettings(name="Tester"), "tester")

    assert await store.name(pixie.id) == "Tester"
    assert await store.name("gone") is None


async def test_reorder_moves_every_pixie_and_names_the_moved_ones(
    db: Database, clock: FakeClock
) -> None:
    store = PixieStore(db, clock)
    a, b, c = [await store.create(PixieSettings(name=n), n.lower()) for n in ("A", "B", "C")]

    moved = await store.reorder([b.id, a.id, c.id])
    listed = await store.list_pixies()

    assert moved == [b.id, a.id]
    assert [(p.id, p.position) for p in listed] == [(b.id, 0), (a.id, 1), (c.id, 2)]


@pytest.mark.parametrize("order", [[0, 1], [0, 1, 1], [0, 1, 2, 2], [0, 1, 3]])
async def test_reorder_must_name_every_pixie_once(
    db: Database, clock: FakeClock, order: list[int]
) -> None:
    store = PixieStore(db, clock)
    ids = [(await store.create(PixieSettings(name=n), n.lower())).id for n in ("A", "B", "C")]
    named = [*ids, "nope"]

    with pytest.raises(InvalidOrderError):
        await store.reorder([named[i] for i in order])

    assert [p.id for p in await store.list_pixies()] == ids
