"""When a queued message starts: as a turn or publishing ends, or after a Stop (B34)."""

import asyncio
from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path

import pytest

from harness.attachments.store import Attachment
from harness.events import types
from harness.providers.base import RewindResult
from harness.sessions.live import LiveSession
from harness.sessions.models import USER, QueuedMessage, Sender, SessionState
from harness.storage.db import Database
from tests.async_support import until
from tests.fake_provider import FakeRun, echoed, reply, until_interrupted
from tests.fakes import FakeClock
from tests.session_support import Env


@pytest.fixture
async def env(tmp_path: Path, db: Database, clock: FakeClock) -> AsyncIterator[Env]:
    environment = Env(tmp_path, db, clock)
    await environment.register()
    yield environment
    await environment.manager.shutdown()


def texts(run: FakeRun) -> list[str]:
    return [user_input.text for user_input in run.inputs]


class SlowAdd:
    """Holds `MessageQueue.add` until released, as a slow database write would."""

    def __init__(self, env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
        self.adding, self.release = asyncio.Event(), asyncio.Event()
        self._add = env.queue.add
        monkeypatch.setattr(env.queue, "add", self.add)

    async def add(
        self,
        session_id: str,
        text: str,
        attachments: list[Attachment],
        urgent: bool = False,
        sender: Sender = USER,
    ) -> QueuedMessage:
        self.adding.set()
        await self.release.wait()
        return await self._add(session_id, text, attachments, urgent, sender)


def live_of(env: Env, session_id: str) -> LiveSession:
    return env.manager._live[session_id]  # pyright: ignore[reportPrivateUsage]


async def test_a_message_queued_as_the_turn_ends_still_starts(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """BUG-85: the turn's end read the queue before the message was in it."""
    release_turn = asyncio.Event()

    async def second_turn(run: FakeRun) -> None:
        await release_turn.wait()
        await reply("two done")(run)

    env.provider.script(reply("one"), second_turn, reply("three done"))
    created = await env.create(prompt="one", mode="in_place", allow_dirty=True)
    await env.reach(created.id, SessionState.IDLE)
    await env.manager.send(created.id, "two", [])
    (run,) = env.provider.runs
    await until(lambda: len(run.inputs) == 2)
    slow = SlowAdd(env, monkeypatch)
    sending = asyncio.ensure_future(env.manager.send(created.id, "three", []))
    await asyncio.wait_for(slow.adding.wait(), 5)

    release_turn.set()
    await until(lambda: not env.manager.busy(created.id))
    slow.release.set()
    sent = await sending
    await until(lambda: len(run.inputs) == 3)
    await env.reach(created.id, SessionState.IDLE)

    assert sent.queued_message is not None
    assert texts(run) == ["one", "two", "three"]
    assert await env.manager.queued(created.id) == []


async def test_a_message_queued_as_publishing_ends_still_starts(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """BUG-85: the end of publishing found nothing to start yet."""
    env.provider.script(reply("one"), reply("two done"))
    created = await env.create(prompt="one", mode="in_place", allow_dirty=True)
    await env.reach(created.id, SessionState.IDLE)
    (run,) = env.provider.runs
    slow = SlowAdd(env, monkeypatch)

    async with env.manager.publishing(created.id):
        sending = asyncio.ensure_future(env.manager.send(created.id, "two", []))
        await asyncio.wait_for(slow.adding.wait(), 5)
    slow.release.set()
    sent = await sending
    await until(lambda: len(run.inputs) == 2)
    await env.reach(created.id, SessionState.IDLE)

    assert sent.queued_message is not None
    assert texts(run) == ["one", "two"]
    assert await env.manager.queued(created.id) == []


async def test_a_message_queued_as_a_stopped_turn_ends_waits(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A Stop holds the queue (BUG-61), also for a message that lands as the turn ends."""
    env.provider.script(reply("one"), until_interrupted(), reply("never"))
    created = await env.create(prompt="one", mode="in_place", allow_dirty=True)
    await env.reach(created.id, SessionState.IDLE)
    await env.manager.send(created.id, "two", [])
    (run,) = env.provider.runs
    await until(lambda: len(run.inputs) == 2)
    slow = SlowAdd(env, monkeypatch)
    sending = asyncio.ensure_future(env.manager.send(created.id, "held", []))
    await asyncio.wait_for(slow.adding.wait(), 5)

    await env.manager.interrupt(created.id)
    await env.reach(created.id, SessionState.INTERRUPTED)
    slow.release.set()
    await sending

    assert texts(run) == ["one", "two"]
    assert [m.text for m in await env.manager.queued(created.id)] == ["held"]
    assert not env.manager.busy(created.id)
    assert (await env.states(created.id))[-1] == "interrupted"


async def test_a_message_held_by_a_finishing_send_waits_after_a_stop(env: Env) -> None:
    """The end of a stopped turn lets go of a message that was held only by a send still
    finishing (BUG-60): the queue then waits, also once publishing ends (BUG-61).
    """
    env.provider.script(reply("one"), reply("two"), reply("never"))
    created = await env.create(prompt="one", mode="in_place", allow_dirty=True)
    await env.reach(created.id, SessionState.IDLE)
    env.provider.send_gate = asyncio.Event()
    await env.manager.send(created.id, "two", [])
    (run,) = env.provider.runs
    await until(lambda: len(run.inputs) == 2)
    await env.reach(created.id, SessionState.IDLE)
    sent = await env.manager.send(created.id, "held", [])
    assert sent.queued_message is not None

    await env.manager.interrupt(created.id)
    await env.reach(created.id, SessionState.INTERRUPTED)
    async with env.manager.publishing(created.id):
        pass

    assert texts(run) == ["one", "two"]
    assert [m.text for m in await env.manager.queued(created.id)] == ["held"]
    assert not env.manager.busy(created.id)


async def test_a_nudge_that_lost_its_queued_message_still_delivers_the_cut_off_one(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The prompt a nudge cut off goes to the agent even when the nudge's own message was
    taken off the queue by the time the start's end looks (BUG-58).
    """
    gate = asyncio.Event()
    env.provider.open_gate = gate
    env.provider.script(reply("on it"))
    created = await env.create(mode="in_place", allow_dirty=True)
    await env.reach(created.id, SessionState.RUNNING)
    turns = env.manager._turns  # pyright: ignore[reportPrivateUsage]
    has_queued = turns._has_queued  # pyright: ignore[reportPrivateUsage]

    async def emptied_first(live: LiveSession) -> bool:
        await env.queue.clear(live.session_id)
        return await has_queued(live)

    monkeypatch.setattr(turns, "_has_queued", emptied_first)
    nudge = await env.manager.send(created.id, "You seem stuck", [], interrupt=True)
    env.provider.open_gate = None
    gate.set()
    await until(lambda: bool(env.provider.runs) and len(env.provider.runs[0].inputs) == 1)
    await env.reach(created.id, SessionState.IDLE)

    assert nudge.queued_message is not None
    assert texts(env.provider.runs[0]) == ["Fix the bug\nDetails here"]
    assert await env.manager.queued(created.id) == []


async def test_a_stopped_session_starts_nothing_from_its_queue(env: Env) -> None:
    """Closing, archiving or shutting down: neither a turn's end nor the end of a hold
    starts a queued message any more (BUG-53).
    """
    env.provider.script(reply("one"))
    created = await env.create(prompt="one", mode="in_place", allow_dirty=True)
    await env.reach(created.id, SessionState.IDLE)
    await env.queue.add(created.id, "queued", [])
    live = live_of(env, created.id)
    live.stopped = True
    turns = env.manager._turns  # pyright: ignore[reportPrivateUsage]

    live.held = True
    await turns.release_held(live)
    live.turn_active = True
    await turns._conclude(live, SessionState.IDLE, None)  # pyright: ignore[reportPrivateUsage]

    assert live.task is None
    assert not live.turn_active
    assert [m.text for m in await env.manager.queued(created.id)] == ["queued"]
    assert texts(env.provider.runs[0]) == ["one"]


async def test_starting_work_lets_go_of_a_hold() -> None:
    """A message held by publishing or a finishing send starts with the next work; a
    later end of publishing must not start the queue beside that work (BUG-60, BUG-61).
    """
    live = LiveSession("s1")
    live.held = True
    done = asyncio.Event()

    async def work() -> None:
        await done.wait()

    live.start(work)
    done.set()
    assert live.task is not None
    await live.task

    assert live.held is False


async def test_a_restore_keeps_the_idle_run_open(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    """An idle close planned before a restore does not close the run under it."""
    env.provider.script(echoed("msg-1", reply("one")))
    created = await env.create(prompt="one", mode="in_place", allow_dirty=True)
    await env.reach(created.id, SessionState.IDLE)
    (run,) = env.provider.runs
    message = await first_user_message(env, created.id)
    restoring, finish = asyncio.Event(), asyncio.Event()
    rewind_files = run.rewind_files

    async def slow_rewind(checkpoint_id: str, dry_run: bool) -> RewindResult:
        restoring.set()
        await finish.wait()
        return await rewind_files(checkpoint_id, dry_run)

    monkeypatch.setattr(run, "rewind_files", slow_rewind)
    live_of(env, created.id).schedule_idle_close(timedelta(milliseconds=20))
    restore = asyncio.ensure_future(env.manager.rewind(created.id, message, dry_run=True))
    await asyncio.wait_for(restoring.wait(), 5)
    await asyncio.sleep(0.2)
    closed_meanwhile = run.closed
    finish.set()
    await restore

    assert closed_meanwhile is False


async def first_user_message(env: Env, session_id: str) -> int:
    events = await env.bus.session_events(session_id)
    return next(e.id for e in events if e.type == types.SESSION_USER_MESSAGE and e.id is not None)
