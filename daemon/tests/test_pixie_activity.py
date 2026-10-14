from datetime import timedelta

from harness.pixies.activity import KEEP, ActivityStore
from harness.pixies.models import PixieSettings
from harness.pixies.store import PixieStore
from harness.storage.db import Database
from tests.fakes import FakeClock


async def test_the_log_is_newest_first_and_per_pixie(db: Database, clock: FakeClock) -> None:
    pixies = PixieStore(db, clock)
    first = await pixies.create(PixieSettings(name="One"), "one")
    second = await pixies.create(PixieSettings(name="Two"), "two")
    log = ActivityStore(db, clock)

    await log.add(first.id, "send_message", "s1", "Sent: hello")
    clock.advance(timedelta(minutes=1))
    await log.add(first.id, "interrupt", "s1", "Stopped the turn")
    await log.add(second.id, "card", None, "Posted a card")

    entries = await log.list(first.id)

    assert [(e.tool, e.session_id, e.summary) for e in entries] == [
        ("interrupt", "s1", "Stopped the turn"),
        ("send_message", "s1", "Sent: hello"),
    ]
    assert entries[0].ts == clock.now()
    assert entries[0].id > entries[1].id
    assert [e.tool for e in await log.list(second.id)] == ["card"]


async def test_only_the_latest_entries_are_kept(db: Database, clock: FakeClock) -> None:
    pixie = await PixieStore(db, clock).create(PixieSettings(name="One"), "one")
    log = ActivityStore(db, clock)

    for n in range(KEEP + 3):
        await log.add(pixie.id, "send_message", None, f"message {n}")
    entries = await log.list(pixie.id)

    assert len(entries) == KEEP
    assert entries[0].summary == f"message {KEEP + 2}"
    assert entries[-1].summary == "message 3"


async def test_deleting_a_pixie_deletes_its_log(db: Database, clock: FakeClock) -> None:
    pixies = PixieStore(db, clock)
    pixie = await pixies.create(PixieSettings(name="One"), "one")
    log = ActivityStore(db, clock)
    await log.add(pixie.id, "interrupt", None, "Stopped")

    await pixies.delete(pixie.id)

    assert await log.list(pixie.id) == []
