"""Pixie reports in SQLite (B42)."""

from datetime import timedelta

import pytest

from nestd.pixies.models import PixieSettings
from nestd.pixies.report_store import LIST_MAX, ReportNotFoundError, ReportStore
from nestd.pixies.store import PixieStore
from nestd.storage.db import Database
from tests.fakes import FakeClock


async def test_add_list_and_read(db: Database, clock: FakeClock) -> None:
    pixies = PixieStore(db, clock)
    boss = await pixies.create(PixieSettings(name="Boss"), "boss")
    other = await pixies.create(PixieSettings(name="Other"), "other")
    store = ReportStore(db, clock)
    first = await store.add(boss.id, "warn", "CI is red", "Two checks fail.", "https://x.test/1")
    clock.advance(timedelta(minutes=1))
    second = await store.add(
        boss.id, "action", "Review waits", "", None, habit=("h1", "Morning check"), run_id="r1"
    )
    clock.advance(timedelta(minutes=1))
    third = await store.add(other.id, "info", "All good", "", None)

    newest_first = [r.id for r in await store.list_reports(unread=False)]
    read, changed = await store.mark_read(first.id)
    again, unchanged = await store.mark_read(first.id)
    unread = [r.id for r in await store.list_reports(unread=True)]
    boss_read = await store.mark_pixie_read(boss.id)
    nothing_left = await store.mark_pixie_read(boss.id)

    assert newest_first == [third.id, second.id, first.id]
    assert first.link == "https://x.test/1"
    assert (first.habit_id, first.habit_name, first.run_id) == (None, None, None)
    assert (second.habit_id, second.habit_name, second.run_id) == ("h1", "Morning check", "r1")
    assert second.created_at == first.created_at + timedelta(minutes=1)
    assert (changed, read.read_at) == (True, clock.now())
    assert (unchanged, again.read_at) == (False, clock.now())
    assert unread == [third.id, second.id]
    assert boss_read == [second.id]
    assert nothing_left == []
    assert (await store.get(second.id)).read_at == clock.now()
    assert (await store.get(third.id)).read_at is None


async def test_unknown_reports(db: Database, clock: FakeClock) -> None:
    store = ReportStore(db, clock)

    with pytest.raises(ReportNotFoundError):
        await store.get("nope")
    with pytest.raises(ReportNotFoundError):
        await store.mark_read("nope")


async def test_only_the_latest_are_listed(db: Database, clock: FakeClock) -> None:
    boss = await PixieStore(db, clock).create(PixieSettings(name="Boss"), "boss")
    store = ReportStore(db, clock)
    for n in range(LIST_MAX + 1):
        clock.advance(timedelta(seconds=1))
        await store.add(boss.id, "info", f"R{n}", "", None)

    listed = await store.list_reports(unread=False)

    assert len(listed) == LIST_MAX
    assert listed[0].title == f"R{LIST_MAX}"
    assert listed[-1].title == "R1"
