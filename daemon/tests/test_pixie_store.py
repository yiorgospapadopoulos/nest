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
