"""Follow-up messages sent while a turn runs (D032)."""

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from pydantic import TypeAdapter

from harness.events import types
from harness.sessions.errors import SessionBusyError
from harness.sessions.live import LiveSession
from harness.sessions.models import QueuedMessage, SessionState
from harness.sessions.queue import QueuedMessageNotFoundError
from harness.storage.db import Database
from tests.async_support import until
from tests.fake_provider import FakeRun, ask, crash, hang, reply, until_interrupted
from tests.fakes import FakeClock
from tests.session_support import Env


@pytest.fixture
async def env(tmp_path: Path, db: Database, clock: FakeClock) -> AsyncIterator[Env]:
    environment = Env(tmp_path, db, clock)
    await environment.register()
    yield environment
    await environment.manager.shutdown()


QUEUE = TypeAdapter(list[QueuedMessage])


async def user_messages(env: Env, session_id: str) -> list[object]:
    return [
        event.payload["text"]
        for event in await env.bus.session_events(session_id)
        if event.type == types.SESSION_USER_MESSAGE
    ]


async def queue_events(env: Env, session_id: str) -> list[list[str]]:
    """The texts of the queue after each change."""
    return [
        [message.text for message in QUEUE.validate_python(event.payload["queued"])]
        for event in await env.bus.session_events(session_id)
        if event.type == types.SESSION_QUEUED
    ]


async def results(env: Env, session_id: str, count: int) -> None:
    async def done() -> bool:
        events = await env.bus.session_events(session_id)
        return len([e for e in events if e.type == types.SESSION_RESULT]) >= count

    await until(done)


async def test_messages_sent_during_a_turn_run_next_in_order_without_going_idle(env: Env) -> None:
    gate = asyncio.Event()

    async def slow(run: FakeRun) -> None:
        await gate.wait()
        await reply("first done")(run)

    env.provider.script(slow, reply("second done"), reply("third done"))
    created = await env.create(prompt="first")
    await env.reach(created.id, SessionState.RUNNING)
    doc = await env.attachments.save("notes.txt", b"hi", "text/plain")

    second = await env.manager.send(created.id, "second", [doc.id])
    third = await env.manager.send(created.id, "third", [])
    queued = await env.manager.queued(created.id)
    gate.set()
    await results(env, created.id, 3)
    await env.reach(created.id, SessionState.IDLE)

    assert second.queued_message is not None
    assert second.queued_message.attachments[0].filename == "notes.txt"
    assert third.queued_message is not None
    assert [m.text for m in queued] == ["second", "third"]
    assert await user_messages(env, created.id) == ["first", "second", "third"]
    assert await env.states(created.id) == ["starting", "running", "running", "running", "idle"]
    assert await queue_events(env, created.id) == [
        ["second"],
        ["second", "third"],
        ["third"],
        [],
    ]
    inputs = [i for run in env.provider.runs for i in run.inputs]
    assert [i.text for i in inputs] == ["first", "second", "third"]
    # The attachment's folder needs a new run, which resumes the conversation.
    assert inputs[1].file_paths == (doc.path,)
    assert env.provider.runs[1].spec.resume_id == "sdk-1"
    assert await env.manager.queued(created.id) == []


async def test_an_interrupt_keeps_the_queue_until_a_turn_ends_normally(env: Env) -> None:
    env.provider.script(until_interrupted(), reply("fresh"), reply("from the queue"))
    created = await env.create(prompt="long job")
    await env.reach(created.id, SessionState.RUNNING)
    await until(lambda: bool(env.provider.runs) and bool(env.provider.runs[0].inputs))

    await env.manager.send(created.id, "later", [])
    await env.manager.interrupt(created.id)
    await env.reach(created.id, SessionState.INTERRUPTED)
    kept = [m.text for m in await env.manager.queued(created.id)]
    await env.manager.send(created.id, "now", [])
    await results(env, created.id, 3)
    await env.reach(created.id, SessionState.IDLE)

    assert kept == ["later"]
    assert await user_messages(env, created.id) == ["long job", "now", "later"]


async def test_an_interrupting_message_stops_the_turn_and_runs_ahead_of_the_queue(
    env: Env,
) -> None:
    env.provider.script(until_interrupted(), reply("nudged"), reply("from the queue"))
    created = await env.create(prompt="long job")
    await env.reach(created.id, SessionState.RUNNING)
    await until(lambda: bool(env.provider.runs) and bool(env.provider.runs[0].inputs))

    await env.manager.send(created.id, "later", [])
    nudge = await env.manager.send(created.id, "try another way", [], interrupt=True)
    await results(env, created.id, 3)
    await env.reach(created.id, SessionState.IDLE)

    assert nudge.queued_message is not None
    assert ("interrupt", None) in env.provider.runs[0].calls
    assert await user_messages(env, created.id) == ["long job", "try another way", "later"]
    # The interrupted turn hands over straight to the nudge, never resting in between.
    assert await env.states(created.id) == ["starting", "running", "running", "running", "idle"]


async def test_an_interrupting_message_expires_the_prompt_the_agent_waits_on(env: Env) -> None:
    env.provider.script(ask("Bash", then=until_interrupted()), reply("nudged"))
    created = await env.create(prompt="risky job")
    await env.reach(created.id, SessionState.WAITING)

    await env.manager.send(created.id, "stop asking", [], interrupt=True)
    await results(env, created.id, 2)
    await env.reach(created.id, SessionState.IDLE)

    (decision,) = env.provider.runs[0].decisions
    assert decision.behavior == "deny"
    assert await user_messages(env, created.id) == ["risky job", "stop asking"]


async def test_a_cancelled_nudge_leaves_the_turn_interrupted(env: Env) -> None:
    gate = asyncio.Event()

    async def slow_stop(run: FakeRun) -> None:
        await run.interrupted.wait()
        await gate.wait()
        await until_interrupted()(run)

    env.provider.script(slow_stop, reply("next"))
    created = await env.create(prompt="long job")
    await env.reach(created.id, SessionState.RUNNING)
    await until(lambda: bool(env.provider.runs) and bool(env.provider.runs[0].inputs))

    nudge = await env.manager.send(created.id, "nudge", [], interrupt=True)
    assert nudge.queued_message is not None
    await env.manager.cancel_queued(created.id, nudge.queued_message.id)
    gate.set()
    await env.reach(created.id, SessionState.INTERRUPTED)
    # A later interrupt-free turn is not affected by the nudge that never ran.
    await env.manager.send(created.id, "fresh", [])
    await results(env, created.id, 2)
    await env.reach(created.id, SessionState.IDLE)

    assert await user_messages(env, created.id) == ["long job", "fresh"]


async def test_an_interrupting_message_to_an_idle_session_just_starts(env: Env) -> None:
    env.provider.script(reply("one"), reply("two"))
    created = await env.create(prompt="one")
    await env.reach(created.id, SessionState.IDLE)

    sent = await env.manager.send(created.id, "two", [], interrupt=True)
    await results(env, created.id, 2)

    assert sent.queued_message is None
    assert ("interrupt", None) not in env.provider.runs[0].calls


async def test_a_failed_turn_keeps_the_queue(env: Env) -> None:
    gate = asyncio.Event()

    async def crash_later(run: FakeRun) -> None:
        await gate.wait()
        await crash("cli crashed")(run)

    env.provider.script(crash_later)
    created = await env.create()
    await env.reach(created.id, SessionState.RUNNING)

    await env.manager.send(created.id, "after the crash", [])
    gate.set()
    await env.reach(created.id, SessionState.FAILED)

    assert [m.text for m in await env.manager.queued(created.id)] == ["after the crash"]


async def test_queued_messages_can_be_cancelled(env: Env) -> None:
    env.provider.script(hang())
    created = await env.create()
    await env.reach(created.id, SessionState.RUNNING)

    first = await env.manager.send(created.id, "one", [])
    await env.manager.send(created.id, "two", [])
    assert first.queued_message is not None
    await env.manager.cancel_queued(created.id, first.queued_message.id)

    assert [m.text for m in await env.manager.queued(created.id)] == ["two"]
    assert (await queue_events(env, created.id))[-1] == ["two"]
    with pytest.raises(QueuedMessageNotFoundError):
        await env.manager.cancel_queued(created.id, first.queued_message.id)


async def test_a_turn_that_ends_before_send_returns_still_delivers_the_queue(
    env: Env,
) -> None:
    turn_gate = asyncio.Event()

    async def quick(run: FakeRun) -> None:
        await turn_gate.wait()
        await reply("two")(run)

    env.provider.script(reply("one"), quick, reply("three"))
    created = await env.create(prompt="one")
    await env.reach(created.id, SessionState.IDLE)
    env.provider.send_gate = asyncio.Event()

    await env.manager.send(created.id, "two", [])
    await until(lambda: len(env.provider.runs[0].inputs) == 2)
    await env.manager.send(created.id, "three", [])
    # The turn ends while the message that started it is still being sent.
    turn_gate.set()
    # The end of a turn reads the connectors last, after it took "three" off the queue and
    # started its delivery. Waiting for that read, not for the queue to empty, keeps the
    # sending task blocked until the task delivering "three" exists and waits for it.
    run = env.provider.runs[0]
    await until(lambda: run.status_calls == 2)

    assert await env.manager.queued(created.id) == []
    assert len(run.inputs) == 2
    env.provider.send_gate.set()
    await results(env, created.id, 3)
    await env.reach(created.id, SessionState.IDLE)

    assert await user_messages(env, created.id) == ["one", "two", "three"]
    assert await env.states(created.id) == [
        "starting",
        "running",
        "idle",
        "running",
        "running",
        "idle",
    ]


async def test_closing_drops_the_queue_and_purging_deletes_it(env: Env) -> None:
    env.provider.script(hang(), hang())
    first = await env.create()
    second = await env.create()
    await env.reach(first.id, SessionState.RUNNING)
    await env.reach(second.id, SessionState.RUNNING)
    await env.manager.send(first.id, "x", [])
    await env.manager.send(second.id, "y", [])

    await env.manager.close(first.id, remove_worktree=True)
    await env.manager.purge(second.id)

    assert await env.manager.queued(first.id) == []
    assert (await queue_events(env, first.id))[-1] == []
    assert await env.queue.messages(second.id) == []


async def test_a_session_never_runs_two_tasks_at_once() -> None:
    live = LiveSession("s1")
    gate = asyncio.Event()

    async def work() -> None:
        await gate.wait()

    live.start(work)

    with pytest.raises(SessionBusyError, match="busy"):
        live.start(work)
    gate.set()
    await live.stop()
