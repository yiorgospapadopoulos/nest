import asyncio
from collections.abc import AsyncIterator
from contextlib import aclosing
from datetime import timedelta

import pytest

from harness.events import types
from harness.events.bus import EventBus, SubscriptionOverflowError
from harness.events.models import Event
from harness.storage.db import Database
from tests.fakes import FakeClock


async def take(events: AsyncIterator[Event], count: int) -> list[Event]:
    return [await anext(events) for _ in range(count)]


def test_event_type_names() -> None:
    assert types.DAEMON_STARTED == "daemon.started"
    assert types.DEVICE_PAIRED == "device.paired"
    assert types.DEVICE_REVOKED == "device.revoked"
    assert types.SESSION_CREATED == "session.created"
    assert types.SESSION_STATE == "session.state"
    assert types.SESSION_WORKSPACE == "session.workspace"
    assert types.SESSION_SETUP_FAILED == "session.setup_failed"
    assert types.SESSION_USER_MESSAGE == "session.user_message"
    assert types.SESSION_MESSAGE == "session.message"
    assert types.SESSION_DELTA == "session.delta"
    assert types.SESSION_RESULT == "session.result"
    assert types.SESSION_GIT_VIOLATION == "session.git_violation"
    assert types.SESSION_TASKS == "session.tasks"
    assert types.SESSION_AGENTS == "session.agents"
    assert types.APPROVAL_CREATED == "approval.created"
    assert types.APPROVAL_RESOLVED == "approval.resolved"
    assert types.GIT_COMMITTED == "git.committed"
    assert types.GIT_PUSHED == "git.pushed"
    assert types.GIT_FAILED == "git.failed"
    assert types.PR_OPENED == "pr.opened"
    assert types.NOTIFY == "notify"
    assert types.USAGE_UPDATED == "usage.updated"


async def test_publish_persists_and_returns_the_event(db: Database, clock: FakeClock) -> None:
    bus = EventBus(db, clock)

    first = await bus.publish("a.b", {"n": 1, "nested": {"list": [1, "x", None]}}, "s1")
    clock.advance(timedelta(seconds=1))
    second = await bus.publish("c.d", {})

    assert first.id is not None
    assert second.id is not None
    assert first.id < second.id
    assert first.type == "a.b"
    assert first.ts == clock.current - timedelta(seconds=1)
    assert first.session_id == "s1"
    assert first.payload == {"n": 1, "nested": {"list": [1, "x", None]}}
    assert second.session_id is None
    async with aclosing(bus.subscribe(after_id=0)) as events:
        assert await take(events, 2) == [first, second]


async def test_replay_starts_after_the_given_id(db: Database, clock: FakeClock) -> None:
    bus = EventBus(db, clock)
    published = [await bus.publish("e", {"i": i}) for i in range(3)]

    async with aclosing(bus.subscribe(after_id=published[0].id or 0)) as events:
        assert await take(events, 2) == published[1:]


async def test_without_after_only_live_events_are_streamed(db: Database, clock: FakeClock) -> None:
    bus = EventBus(db, clock)
    await bus.publish("old", {})

    async with aclosing(bus.subscribe()) as events:
        pending = asyncio.ensure_future(anext(events))
        await asyncio.sleep(0)
        live = await bus.publish("new", {})
        assert await pending == live


async def test_replay_then_live_without_gaps(db: Database, clock: FakeClock) -> None:
    bus = EventBus(db, clock)
    before = await bus.publish("before", {})

    async with aclosing(bus.subscribe(after_id=0)) as events:
        first = await anext(events)
        during = await bus.publish("during", {})
        after = await bus.publish("after", {})
        rest = await take(events, 2)

    assert [first, *rest] == [before, during, after]


async def test_event_in_backlog_and_live_queue_is_delivered_once(
    db: Database, clock: FakeClock
) -> None:
    bus = EventBus(db, clock)
    events = bus.subscribe(after_id=0)
    async with aclosing(events):
        # The publish is mid-insert when the subscriber registers, so the event reaches
        # both the live queue and the backlog query.
        publishing = asyncio.ensure_future(bus.publish("racing", {}))
        await asyncio.sleep(0)
        first_step = asyncio.ensure_future(anext(events))
        racing = await publishing
        assert await first_step == racing
        later = await bus.publish("later", {})
        assert await anext(events) == later


async def test_slow_subscriber_overflows_and_is_dropped(db: Database, clock: FakeClock) -> None:
    bus = EventBus(db, clock, queue_size=2)
    events = bus.subscribe()
    async with aclosing(events):
        pending = asyncio.ensure_future(anext(events))
        await asyncio.sleep(0)
        first = await bus.publish("1", {})
        assert await pending == first
        await bus.publish("2", {})
        await bus.publish("3", {})
        await bus.publish("4", {})
        assert bus.subscriber_count == 0
        assert [event.type for event in await take(events, 2)] == ["2", "3"]
        with pytest.raises(SubscriptionOverflowError, match="reconnect"):
            await anext(events)


async def test_closing_a_subscription_unregisters_it(db: Database, clock: FakeClock) -> None:
    bus = EventBus(db, clock)
    await bus.publish("x", {})
    async with aclosing(bus.subscribe(after_id=0)) as events:
        await anext(events)
        assert bus.subscriber_count == 1

    assert bus.subscriber_count == 0


async def test_ephemeral_events_reach_live_subscribers_without_being_stored(
    db: Database, clock: FakeClock
) -> None:
    bus = EventBus(db, clock)
    persisted = await bus.publish("kept", {})

    async with aclosing(bus.subscribe(after_id=persisted.id)) as events:
        pending = asyncio.ensure_future(anext(events))
        await asyncio.sleep(0)
        delta = await bus.publish_ephemeral("session.delta", {"text": "hi"}, "s1")
        assert await pending == delta
        second = await bus.publish_ephemeral("session.delta", {"text": "again"}, "s1")
        assert await anext(events) == second

    assert delta.id is None
    assert delta.ts == clock.current
    assert delta.session_id == "s1"
    assert delta.payload == {"text": "hi"}
    rows = await db.fetch_all("SELECT type FROM events")
    assert [row["type"] for row in rows] == ["kept"]
    async with aclosing(bus.subscribe(after_id=0)) as replay:
        assert await anext(replay) == persisted
        later = await bus.publish("later", {})
        assert await anext(replay) == later


async def test_session_events_returns_one_sessions_persisted_events(
    db: Database, clock: FakeClock
) -> None:
    bus = EventBus(db, clock)
    first = await bus.publish("a", {"n": 1}, "s1")
    await bus.publish("b", {}, "s2")
    await bus.publish("c", {})
    second = await bus.publish("d", {"n": 2}, "s1")

    assert await bus.session_events("s1") == [first, second]
    assert await bus.session_events("s1", after_id=first.id or 0) == [second]
    assert await bus.session_events("missing") == []
