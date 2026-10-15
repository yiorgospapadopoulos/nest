"""The queue's record of messages written into a running turn (B59)."""

import pytest

from nestd.events.bus import EventBus
from nestd.sessions.queue import MessageQueue, QueuedMessageNotFoundError
from nestd.sessions.store import SessionStore
from nestd.storage.db import Database
from tests.fakes import FakeClock
from tests.test_session_store import new_session


async def queue_with_sessions(db: Database, clock: FakeClock) -> tuple[MessageQueue, str, str]:
    store = SessionStore(db, clock)
    first = await store.create(new_session())
    second = await store.create(new_session())
    return MessageQueue(db, clock, EventBus(db, clock)), first.id, second.id


async def test_sent_messages_wait_again_for_one_session_or_all(
    db: Database, clock: FakeClock
) -> None:
    queue, one, two = await queue_with_sessions(db, clock)
    a = await queue.add(one, "a", [], sent=True)
    await queue.add(one, "b", [])
    await queue.add(two, "c", [], sent=True)

    assert await queue.sent_ids(one) == [a.id]
    assert [m.text for m in await queue.waiting(one)] == ["b"]
    await queue.unsend_all(one)
    assert await queue.sent_ids(one) == []
    assert [m.text for m in await queue.waiting(two)] == []
    await queue.unsend_all()
    assert [m.text for m in await queue.waiting(two)] == ["c"]


async def test_marking_messages_announces_only_a_change(db: Database, clock: FakeClock) -> None:
    store = SessionStore(db, clock)
    session = await store.create(new_session())
    bus = EventBus(db, clock)
    queue = MessageQueue(db, clock, bus)
    message = await queue.add(session.id, "a", [])

    await queue.mark_sent(session.id, [message.id], False)
    await queue.mark_sent(session.id, [], True)
    await queue.mark_sent(session.id, [message.id], True)

    announced = [e for e in await bus.session_events(session.id) if e.type == "session.queued"]
    assert len(announced) == 2
    assert (await queue.get(session.id, message.id)).sent is True


async def test_unknown_messages(db: Database, clock: FakeClock) -> None:
    queue, one, two = await queue_with_sessions(db, clock)
    message = await queue.add(one, "a", [])

    assert await queue.take(two, message.id) is None
    with pytest.raises(QueuedMessageNotFoundError):
        await queue.get(two, message.id)
    with pytest.raises(QueuedMessageNotFoundError):
        await queue.make_urgent(two, message.id)
    taken = await queue.take(one, message.id)
    assert taken is not None
    assert taken.text == "a"
    assert await queue.messages(one) == []


async def test_removing_an_unknown_message_is_refused(db: Database, clock: FakeClock) -> None:
    queue, one, _ = await queue_with_sessions(db, clock)

    with pytest.raises(QueuedMessageNotFoundError):
        await queue.cancel(one, "nope")
