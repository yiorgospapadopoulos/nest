"""Stuck detection (B14, D036)."""

import asyncio
import logging
from datetime import timedelta

import pytest
from pydantic import JsonValue

from harness.config.models import StuckSettings
from harness.events import types
from harness.events.bus import EventBus
from harness.events.models import Event
from harness.notifications.notifier import Notifier
from harness.sessions.models import Session
from harness.sessions.store import SessionStore
from harness.storage.db import Database
from harness.stuck.models import StuckFlag
from harness.stuck.watcher import StuckWatcher
from tests.async_support import until
from tests.fakes import FakeClock
from tests.test_session_store import new_session


class Env:
    def __init__(self, db: Database, clock: FakeClock) -> None:
        self.clock = clock
        self.bus = EventBus(db, clock)
        self.store = SessionStore(db, clock)
        self.settings = StuckSettings()
        self.watcher = StuckWatcher(
            store=self.store,
            bus=self.bus,
            notifier=Notifier(self.bus),
            clock=clock,
            settings=lambda: self.settings,
            tick=timedelta(milliseconds=10),
        )

    async def running(self) -> Session:
        session = await self.store.create(new_session(title="Fix login"))
        await self.state(session, "running")
        return session

    async def send(self, session: Session, event_type: str, payload: dict[str, JsonValue]) -> Event:
        event = await self.bus.publish(event_type, payload, session.id)
        await self.watcher.observe(event)
        return event

    async def state(self, session: Session, state: str) -> None:
        await self.send(session, types.SESSION_STATE, {"state": state, "error": None})

    async def ephemeral(
        self, session: Session, event_type: str, payload: dict[str, JsonValue]
    ) -> None:
        await self.watcher.observe(
            await self.bus.publish_ephemeral(event_type, payload, session.id)
        )

    async def output(self, session: Session) -> None:
        event = await self.bus.publish_ephemeral(types.SESSION_DELTA, {"text": "x"}, session.id)
        await self.watcher.observe(event)

    async def call(
        self,
        session: Session,
        tool: str = "Bash",
        tool_input: dict[str, JsonValue] | None = None,
        parent: str | None = None,
    ) -> None:
        block: dict[str, JsonValue] = {
            "type": "tool_use",
            "id": "t",
            "name": tool,
            "input": tool_input if tool_input is not None else {"command": "make test"},
        }
        await self.send(
            session, types.SESSION_MESSAGE, {"blocks": [block], "parent_tool_use_id": parent}
        )

    async def prompt(self, session: Session, approval_id: str, kind: str, status: str) -> None:
        event_type = types.APPROVAL_CREATED if status == "pending" else types.APPROVAL_RESOLVED
        approval: dict[str, JsonValue] = {"id": approval_id, "kind": kind, "status": status}
        await self.send(session, event_type, {"approval": approval})

    async def wait(self, minutes: float) -> None:
        self.clock.advance(timedelta(minutes=minutes))
        await self.watcher.tick()

    async def flags(self, session: Session) -> list[tuple[str, JsonValue]]:
        """session.stuck reasons and session.unstuck events, in order."""
        return [
            ("stuck", e.payload["reason"]) if e.type == types.SESSION_STUCK else ("unstuck", None)
            for e in await self.bus.session_events(session.id)
            if e.type in (types.SESSION_STUCK, types.SESSION_UNSTUCK)
        ]

    async def notices(self, session: Session) -> list[JsonValue]:
        return [
            e.payload["text"]
            for e in await self.bus.session_events(session.id)
            if e.type == types.NOTIFY and e.payload["kind"] == "stuck"
        ]

    async def stuck(self, session: Session) -> StuckFlag | None:
        return (await self.store.get(session.id)).stuck


@pytest.fixture
def env(db: Database, clock: FakeClock) -> Env:
    return Env(db, clock)


@pytest.mark.parametrize(
    ("kind", "waiting_on"),
    [("permission", "your approval"), ("question", "your answer"), ("plan", "your plan review")],
)
async def test_waiting_on_a_prompt_too_long(env: Env, kind: str, waiting_on: str) -> None:
    session = await env.running()
    await env.wait(1)
    asked = env.clock.now()
    await env.prompt(session, "a1", kind, "pending")
    await env.state(session, "waiting")

    await env.wait(14)
    assert await env.stuck(session) is None
    await env.wait(1)
    await env.wait(5)

    flag = StuckFlag(
        reason="waiting", since=asked, details=f"Waiting for {waiting_on} for 15 minutes"
    )
    assert await env.stuck(session) == flag
    (published,) = [
        e.payload for e in await env.bus.session_events(session.id) if e.type == types.SESSION_STUCK
    ]
    assert published == flag.model_dump(mode="json")
    assert await env.notices(session) == [f"Waiting for {waiting_on} for 15 minutes"]

    await env.prompt(session, "a1", kind, "resolved")

    assert await env.stuck(session) is None
    assert await env.flags(session) == [("stuck", "waiting"), ("unstuck", None)]
    unstuck = (await env.bus.session_events(session.id))[-1]
    assert unstuck.payload == {"reason": "waiting"}


async def test_running_without_output_and_again_without_a_second_notice(env: Env) -> None:
    session = await env.running()
    await env.wait(9)
    await env.output(session)
    await env.wait(9)
    assert await env.flags(session) == []

    await env.wait(1)
    flag = await env.stuck(session)
    assert flag is not None
    assert (flag.reason, flag.details) == ("silent", "No new output for 10 minutes")
    await env.output(session)
    await env.wait(10)

    assert await env.flags(session) == [("stuck", "silent"), ("unstuck", None), ("stuck", "silent")]
    assert await env.notices(session) == ["No new output for 10 minutes"]


async def test_thinking_is_activity_and_long_thinking_is_not_silence(env: Env) -> None:
    """IMP-15: thinking streams no text, but the agent is working."""
    session = await env.running()
    await env.wait(9)
    await env.ephemeral(session, types.SESSION_THINKING, {"active": True})
    await env.wait(30)
    assert await env.flags(session) == []

    await env.ephemeral(session, types.SESSION_THINKING, {"active": False})
    await env.wait(9)
    assert await env.flags(session) == []
    await env.wait(1)

    assert await env.flags(session) == [("stuck", "silent")]


async def test_a_notice_is_activity(env: Env) -> None:
    """IMP-30: an engine notice (a retry, a compaction) shows the turn is alive."""
    session = await env.running()
    await env.wait(9)
    await env.send(session, types.SESSION_NOTICE, {"kind": "api_retry", "text": "Retrying"})
    await env.wait(9)

    assert await env.flags(session) == []


async def test_no_silence_while_a_prompt_waits_and_no_flags_once_the_turn_ends(env: Env) -> None:
    session = await env.running()
    await env.prompt(session, "a1", "question", "pending")
    await env.prompt(session, "r1", "review", "pending")
    await env.wait(12)
    assert await env.flags(session) == []

    await env.state(session, "idle")
    await env.wait(120)

    assert await env.flags(session) == []


async def test_the_same_tool_call_over_and_over(env: Env) -> None:
    session = await env.running()
    for _ in range(4):
        await env.call(session, tool_input={"command": "make test", "timeout": 5})
    # Subagents keep their own count, and key order in the input does not matter.
    await env.call(session, tool="Read", parent="agent-1")
    assert await env.flags(session) == []

    await env.call(session, tool_input={"timeout": 5, "command": "make test"})

    flag = await env.stuck(session)
    assert flag is not None
    assert (flag.reason, flag.details) == (
        "repeating",
        "Called Bash 5 times in a row with the same input",
    )
    await env.call(session)
    assert await env.flags(session) == [("stuck", "repeating"), ("unstuck", None)]


async def test_a_subagent_repeating_itself_counts_too(env: Env) -> None:
    env.settings = StuckSettings(repeated_calls=2)
    session = await env.running()
    for _ in range(3):
        await env.call(session, tool="Grep", tool_input={"pattern": "x"}, parent="agent-1")
        await env.call(session, tool="Read", tool_input={"file_path": "/a"})

    flag = await env.stuck(session)
    assert flag is not None
    assert flag.details == "Called Grep 3 times in a row with the same input"


async def test_a_long_turn_until_it_ends(env: Env) -> None:
    session = await env.running()
    started = env.clock.now()
    for _ in range(11):
        await env.wait(5)
        await env.output(session)
    assert await env.flags(session) == []

    await env.wait(5)

    assert await env.stuck(session) == StuckFlag(
        reason="long_turn", since=started, details="The turn has run for 60 minutes"
    )
    await env.state(session, "interrupted")
    assert await env.stuck(session) is None
    assert await env.flags(session) == [("stuck", "long_turn"), ("unstuck", None)]


async def test_a_message_delivered_without_leaving_running_starts_a_new_turn(env: Env) -> None:
    session = await env.running()
    for _ in range(5):
        await env.call(session)
    await env.wait(9)
    await env.output(session)
    await env.wait(9)
    assert await env.notices(session) == ["Called Bash 5 times in a row with the same input"]

    await env.send(session, types.SESSION_USER_MESSAGE, {"text": "nudge", "attachments": []})
    assert await env.stuck(session) is None
    for _ in range(5):
        await env.call(session)
    for _ in range(6):
        await env.wait(9)
        await env.output(session)

    # Counted from the new turn: 54 minutes, so no long turn yet, and notified again.
    assert await env.flags(session) == [
        ("stuck", "repeating"),
        ("unstuck", None),
        ("stuck", "repeating"),
    ]
    assert len(await env.notices(session)) == 2


async def test_the_most_pressing_condition_shows_and_hands_over(env: Env) -> None:
    session = await env.running()
    for _ in range(5):
        await env.wait(9)
        await env.output(session)
    await env.prompt(session, "a1", "permission", "pending")
    await env.wait(15)
    shown = await env.stuck(session)
    assert shown is not None
    assert shown.reason == "waiting"

    await env.prompt(session, "a1", "permission", "resolved")

    flag = await env.stuck(session)
    assert flag is not None
    assert flag.reason == "long_turn"
    assert await env.flags(session) == [("stuck", "waiting"), ("stuck", "long_turn")]
    assert await env.notices(session) == [
        "Waiting for your approval for 15 minutes",
        "The turn has run for 60 minutes",
    ]


async def test_zero_turns_a_check_off_and_settings_apply_at_once(env: Env) -> None:
    env.settings = StuckSettings(
        waiting_minutes=0, silent_minutes=0, repeated_calls=0, turn_minutes=0
    )
    session = await env.running()
    await env.prompt(session, "a1", "permission", "pending")
    for _ in range(9):
        await env.call(session)
    await env.wait(600)
    assert await env.flags(session) == []

    env.settings = StuckSettings(waiting_minutes=1)
    await env.wait(0)

    flag = await env.stuck(session)
    assert flag is not None
    assert flag.details == "Waiting for your approval for 600 minutes"


async def test_one_minute_reads_singular(env: Env) -> None:
    env.settings = StuckSettings(silent_minutes=1)
    session = await env.running()

    await env.wait(1)

    flag = await env.stuck(session)
    assert flag is not None
    assert flag.details == "No new output for 1 minute"


async def test_events_outside_a_turn_or_odd_ones_change_nothing(env: Env) -> None:
    session = await env.store.create(new_session())
    await env.call(session)
    await env.state(session, "starting")
    await env.watcher.observe(await env.bus.publish(types.DEVICE_REVOKED, {"device_id": "1"}))
    running = await env.running()
    await env.send(running, types.SESSION_PR, {"pr": None})
    await env.send(running, types.APPROVAL_CREATED, {"approval": "odd"})
    await env.send(running, types.SESSION_MESSAGE, {"blocks": "odd"})
    await env.send(running, types.SESSION_MESSAGE, {"blocks": ["odd", {"type": "text"}]})
    await env.wait(5)

    assert await env.flags(session) == []
    assert await env.flags(running) == []


async def test_deleted_sessions_are_forgotten(env: Env) -> None:
    session = await env.running()
    other = await env.running()
    await env.watcher.observe(
        await env.bus.publish(types.SESSION_DELETED, {"session_id": session.id})
    )
    await env.store.delete(other.id)

    await env.wait(30)
    await env.wait(30)

    assert await env.flags(session) == []


async def test_start_clears_flags_left_by_a_previous_process_then_follows_events(
    env: Env,
) -> None:
    old = await env.store.create(new_session())
    await env.store.set_stuck(
        old.id, StuckFlag(reason="silent", since=env.clock.now(), details="x")
    )
    env.settings = StuckSettings(repeated_calls=1)
    await env.watcher.start()
    try:
        assert await env.flags(old) == [("unstuck", None)]
        assert (await env.store.get(old.id)).stuck is None
        session = await env.store.create(new_session())
        await asyncio.sleep(0)
        await env.bus.publish(types.SESSION_STATE, {"state": "running"}, session.id)
        for _ in range(2):
            await env.bus.publish(
                types.SESSION_MESSAGE,
                {"blocks": [{"type": "tool_use", "name": "Bash", "input": {}}]},
                session.id,
            )

        async def flagged() -> bool:
            return (await env.store.get(session.id)).stuck is not None

        await until(flagged)
        env.settings = StuckSettings(silent_minutes=1, repeated_calls=0)
        env.clock.advance(timedelta(minutes=2))

        async def silent() -> bool:
            flag = (await env.store.get(session.id)).stuck
            return flag is not None and flag.reason == "silent"

        await until(silent)
    finally:
        await env.watcher.stop()
        await env.watcher.stop()


async def test_failures_and_falling_behind_are_logged_and_survived(
    env: Env, db: Database, caplog: pytest.LogCaptureFixture
) -> None:
    env.bus = EventBus(db, env.clock, queue_size=1)
    gate = asyncio.Event()
    seen: list[str] = []
    ticks = 0

    async def observe(event: Event) -> None:
        seen.append(event.type)
        if event.type == "boom":
            raise RuntimeError("boom")
        await gate.wait()

    async def tick() -> None:
        nonlocal ticks
        ticks += 1
        raise ValueError("tick")

    watcher = StuckWatcher(
        store=env.store,
        bus=env.bus,
        notifier=Notifier(env.bus),
        clock=env.clock,
        settings=lambda: env.settings,
        tick=timedelta(milliseconds=5),
    )
    watcher.observe = observe  # type: ignore[method-assign]
    watcher.tick = tick  # type: ignore[method-assign]
    with caplog.at_level(logging.WARNING):
        await watcher.start()
        try:
            await asyncio.sleep(0)
            await env.bus.publish("boom", {})
            await until(lambda: seen == ["boom"])
            await env.bus.publish("first", {})
            await until(lambda: seen == ["boom", "first"])
            # The watcher is stuck on "first"; these overflow its queue.
            for name in ("second", "third", "fourth"):
                await env.bus.publish(name, {})
            gate.set()
            await until(lambda: "fell behind" in caplog.text)
            await until(lambda: ticks >= 2)
            await env.bus.publish("again", {})
            await until(lambda: seen[-1] == "again")
        finally:
            await watcher.stop()
    assert "stuck check failed (RuntimeError)" in caplog.text
    assert "stuck check failed (ValueError)" in caplog.text
    # Following again picks up after the last event seen, so none is missed (BUG-21).
    assert seen == ["boom", "first", "second", "third", "fourth", "again"]


async def test_a_turn_that_ends_during_a_check_keeps_no_flag(env: Env) -> None:
    """PL-02: a check that was already under way does not flag a turn that has ended."""
    first, second = await env.running(), await env.running()
    env.clock.advance(timedelta(minutes=10))
    real_set_stuck = env.store.set_stuck
    entered, gate = asyncio.Event(), asyncio.Event()

    async def slow_set_stuck(session_id: str, flag: StuckFlag | None) -> Session:
        if session_id == first.id and flag is not None:
            entered.set()
            await gate.wait()  # the database is busy for a moment
        return await real_set_stuck(session_id, flag)

    env.store.set_stuck = slow_set_stuck  # type: ignore[method-assign]
    ticking = asyncio.ensure_future(env.watcher.tick())
    await asyncio.wait_for(entered.wait(), 5)
    ending = asyncio.ensure_future(env.state(second, "idle"))
    await asyncio.sleep(0.01)
    gate.set()
    await asyncio.gather(ticking, ending)
    await env.state(second, "running")
    await env.state(second, "idle")

    assert await env.stuck(second) is None
    assert (await env.flags(second))[-1:] in ([], [("unstuck", None)])


async def test_a_pixie_chat_is_never_flagged(env: Env, db: Database) -> None:
    # Neither the inbox on the iPhone nor the Mac's shows a pixie chat's stuck card (D072).
    await db.execute(
        "INSERT INTO pixies (id, slug, name, mascot, color, background, permission_mode,"
        " autonomy, project_access, skills, can_call, position, created_at, updated_at)"
        " VALUES ('p1', 't', 'T', 'sprout', '#000000', 'plain', 'default', 'observe', 'none',"
        " '[]', '[]', 0, 'x', 'x')"
    )
    session = await env.store.create(new_session(repo="pixie:p1", pixie_id="p1"))
    await env.state(session, "running")

    await env.wait(120)
    await env.wait(1)

    assert await env.stuck(session) is None
    assert await env.flags(session) == []
    assert await env.notices(session) == []
