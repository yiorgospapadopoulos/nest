import sqlite3

import pytest

from harness.pixies.errors import DuplicateSlugError, PixieNotFoundError
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


async def test_create_re_raises_other_integrity_errors(
    db: Database, clock: FakeClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = PixieStore(db, clock)

    async def refuse(sql: str, params: tuple[object, ...] = ()) -> int:
        raise sqlite3.IntegrityError("FOREIGN KEY constraint failed")

    monkeypatch.setattr(db, "execute", refuse)

    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        await store.create(PixieSettings(name="Tester"), "tester")


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
