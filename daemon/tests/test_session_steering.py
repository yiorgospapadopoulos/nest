"""B59: a message sent while a turn runs goes into that turn, as in Claude Code."""

import asyncio
from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path

import pytest
from pydantic import TypeAdapter

from nestd.events import types
from nestd.providers.base import TextBlock
from nestd.sessions.errors import MessageTakenError, NoTurnInProgressError
from nestd.sessions.models import QueuedMessage, SessionState
from nestd.sessions.queue import QueuedMessageNotFoundError
from nestd.storage.db import Database
from tests.async_support import until
from tests.fake_provider import (
    RESULT,
    FakeRun,
    Turn,
    crash,
    engine_error,
    reply,
    until_interrupted,
)
from tests.fakes import FakeClock
from tests.session_support import Env, gate_worktree_add

QUEUE = TypeAdapter(list[QueuedMessage])


@pytest.fixture
async def env(tmp_path: Path, db: Database, clock: FakeClock) -> AsyncIterator[Env]:
    environment = Env(tmp_path, db, clock)
    environment.provider.steering = True
    await environment.register()
    yield environment
    await environment.manager.shutdown()


async def transcript(env: Env, session_id: str) -> list[str]:
    """User messages and the agent's text, in the order the chat shows them."""
    shown: list[str] = []
    for event in await env.bus.session_events(session_id):
        if event.type == types.SESSION_USER_MESSAGE:
            shown.append(f"user: {event.payload['text']}")
        elif event.type == types.SESSION_MESSAGE:
            blocks = event.payload["blocks"]
            assert isinstance(blocks, list)
            for block in blocks:
                assert isinstance(block, dict)
                shown.append(f"agent: {block['text']}")
    return shown


async def result_count(env: Env, session_id: str) -> int:
    events = await env.bus.session_events(session_id)
    return len([e for e in events if e.type == types.SESSION_RESULT])


async def queue_states(env: Env, session_id: str) -> list[list[tuple[str, bool]]]:
    """The queue after each change: each message's text and whether it was sent."""
    return [
        [(m.text, m.sent) for m in QUEUE.validate_python(event.payload["queued"])]
        for event in await env.bus.session_events(session_id)
        if event.type == types.SESSION_QUEUED
    ]


async def results(env: Env, session_id: str) -> list[dict[str, object]]:
    events = await env.bus.session_events(session_id)
    return [dict(e.payload) for e in events if e.type == types.SESSION_RESULT]


async def idle_after(env: Env, session_id: str, results: int) -> None:
    async def done() -> bool:
        states = await env.states(session_id)
        return await result_count(env, session_id) == results and states[-1] == "idle"

    await until(done)


def gated(gate: asyncio.Event, then: Turn) -> Turn:
    async def turn(run: FakeRun) -> None:
        await run.sink.message([TextBlock(text="working")], None)
        await gate.wait()
        await then(run)

    return turn


def reads_then(text: str) -> Turn:
    """The agent reads the messages written into its turn at a step, then answers."""

    async def turn(run: FakeRun) -> None:
        await run.read_steered()
        await reply(text)(run)

    return turn


async def running(env: Env, prompt: str = "first") -> str:
    created = await env.create(prompt=prompt, mode="in_place")
    await env.reach(created.id, SessionState.RUNNING)
    # The prompt is given: the turn runs and nothing else is being set up.
    await until(lambda: env.manager._live[created.id].task is None)  # pyright: ignore[reportPrivateUsage]
    return created.id


async def test_a_message_sent_mid_turn_is_read_in_that_turn_with_one_result(env: Env) -> None:
    gate = asyncio.Event()
    env.provider.script(gated(gate, reads_then("both done")))
    session_id = await running(env)

    sent = await env.manager.send(session_id, "also check the tests", [])
    pending = await env.manager.queued(session_id)
    gate.set()
    await idle_after(env, session_id, 1)

    (run,) = env.provider.runs
    assert sent.queued_message is not None
    assert sent.queued_message.sent is True
    assert [(m.text, m.sent) for m in pending] == [("also check the tests", True)]
    assert [i.text for i in run.inputs] == ["first"]
    assert ("steer", sent.queued_message.id) in run.calls
    # Shown where the agent read it, once, inside the same turn.
    assert await transcript(env, session_id) == [
        "user: first",
        "agent: working",
        "user: also check the tests",
        "agent: both done",
    ]
    assert await env.states(session_id) == ["starting", "running", "idle"]
    assert await queue_states(env, session_id) == [[("also check the tests", True)], []]
    events = await env.bus.session_events(session_id)
    (_, read) = [e.id for e in events if e.type == types.SESSION_USER_MESSAGE]
    assert read is not None
    assert await env.store.checkpoint(session_id, read) == f"cp-{sent.queued_message.id}"
    assert len(env.hooks.starts) == 1


async def test_a_message_the_agent_did_not_read_starts_the_next_turn(env: Env) -> None:
    gate = asyncio.Event()
    env.provider.script(gated(gate, reply("first done")), reply("second done"))
    session_id = await running(env)

    sent = await env.manager.send(session_id, "second", [])
    gate.set()
    await idle_after(env, session_id, 2)

    (run,) = env.provider.runs
    assert sent.queued_message is not None
    # Taken back as the turn ended, then given as the next turn's message.
    assert ("withdraw", sent.queued_message.id) in run.calls
    assert [i.text for i in run.inputs] == ["first", "second"]
    assert await transcript(env, session_id) == [
        "user: first",
        "agent: working",
        "agent: first done",
        "user: second",
        "agent: second done",
    ]
    assert await env.states(session_id) == ["starting", "running", "running", "idle"]
    assert await queue_states(env, session_id) == [[("second", True)], [("second", False)], []]


async def test_a_message_read_as_the_turn_ends_starts_the_agents_next_turn(env: Env) -> None:
    """Claude Code took it off its queue for its next turn before Nest could take it back."""
    gate = asyncio.Event()

    async def turn(run: FakeRun) -> None:
        await gate.wait()
        (message_id, _), *_ = run.steered
        run.steered.clear()
        await reply("first done")(run)
        await run.sink.message_taken(message_id, "cp-next")
        await reply("second done")(run)

    env.provider.script(turn)
    session_id = await running(env)

    await env.manager.send(session_id, "second", [])
    gate.set()
    await idle_after(env, session_id, 2)

    (run,) = env.provider.runs
    assert [i.text for i in run.inputs] == ["first"]
    assert await transcript(env, session_id) == [
        "user: first",
        "agent: first done",
        "user: second",
        "agent: second done",
    ]
    # The session never rests in between, and the new turn starts as a message turn.
    assert await env.states(session_id) == ["starting", "running", "running", "idle"]
    events = await env.bus.session_events(session_id)
    starts = [e.payload for e in events if e.type == types.SESSION_STATE][1:3]
    assert all(start.get("turn_start") is True for start in starts)
    assert len(env.hooks.starts) == 2
    second = [e.id for e in events if e.type == types.SESSION_USER_MESSAGE][1]
    assert second is not None
    assert await env.store.checkpoint(session_id, second) == "cp-next"


async def test_a_message_the_engine_echoes_after_the_chat_rested_starts_a_turn(env: Env) -> None:
    """After a failed turn Claude Code may still run a message it had read: its echo
    then starts a turn of its own.
    """
    gate = asyncio.Event()
    env.provider.script(gated(gate, engine_error("overloaded")))
    session_id = await running(env)
    sent = await env.manager.send(session_id, "late", [])
    assert sent.queued_message is not None
    message_id = sent.queued_message.id
    (run,) = env.provider.runs
    run.steered.clear()
    gate.set()
    await env.reach(session_id, SessionState.FAILED)
    assert [(m.text, m.sent) for m in await env.manager.queued(session_id)] == [("late", False)]

    run.emit(lambda r: _taken_then_reply(r, message_id))
    await idle_after(env, session_id, 2)

    assert await transcript(env, session_id) == [
        "user: first",
        "agent: working",
        "user: late",
        "agent: later done",
    ]
    assert await env.states(session_id) == ["starting", "running", "failed", "running", "idle"]
    assert await env.manager.queued(session_id) == []


async def _taken_then_reply(run: FakeRun, message_id: str) -> None:
    await run.sink.message_taken(message_id, "cp-late")
    await reply("later done")(run)


async def test_send_now_stops_the_turn_and_starts_the_message_right_after(env: Env) -> None:
    env.provider.script(until_interrupted(), reply("now done"))
    session_id = await running(env)
    sent = await env.manager.send(session_id, "do this instead", [])
    assert sent.queued_message is not None

    await env.manager.send_now(session_id, sent.queued_message.id)
    await idle_after(env, session_id, 2)

    (run,) = env.provider.runs
    assert ("withdraw", sent.queued_message.id) in run.calls
    assert ("interrupt", None) in run.calls
    assert [i.text for i in run.inputs] == ["first", "do this instead"]
    assert await transcript(env, session_id) == [
        "user: first",
        "user: do this instead",
        "agent: now done",
    ]
    assert await env.states(session_id) == ["starting", "running", "running", "idle"]
    # The stopped turn's result is a handoff to the message, not a failure to show.
    (stopped, done) = await results(env, session_id)
    assert stopped["handoff"] is True
    assert "stopped" not in stopped
    assert "handoff" not in done


async def test_send_now_leaves_a_message_the_agent_already_read_in_its_turn(env: Env) -> None:
    gate = asyncio.Event()

    async def turn(run: FakeRun) -> None:
        await gate.wait()
        await reads_then("read it")(run)

    env.provider.script(turn)
    session_id = await running(env)
    sent = await env.manager.send(session_id, "steer", [])
    assert sent.queued_message is not None
    (run,) = env.provider.runs
    taken = list(run.steered)
    run.steered.clear()  # Claude Code is reading it at this step

    await env.manager.send_now(session_id, sent.queued_message.id)
    run.steered = taken
    gate.set()
    await idle_after(env, session_id, 1)

    assert ("interrupt", None) not in run.calls
    assert await transcript(env, session_id) == ["user: first", "user: steer", "agent: read it"]


async def test_stop_takes_back_unread_messages_which_then_wait(env: Env) -> None:
    env.provider.script(until_interrupted())
    session_id = await running(env)
    sent = await env.manager.send(session_id, "later", [])
    assert sent.queued_message is not None

    await env.manager.interrupt(session_id)
    await env.reach(session_id, SessionState.INTERRUPTED)

    (run,) = env.provider.runs
    assert run.calls.index(("withdraw", sent.queued_message.id)) < run.calls.index(
        ("interrupt", None)
    )
    assert [(m.text, m.sent) for m in await env.manager.queued(session_id)] == [("later", False)]
    assert [i.text for i in run.inputs] == ["first"]
    assert await transcript(env, session_id) == ["user: first"]
    # A turn the user stopped is no failure either: clients show only its stopped line.
    (stopped,) = await results(env, session_id)
    assert stopped["stopped"] is True
    assert "handoff" not in stopped


async def test_a_message_the_agent_read_before_a_stop_waits_again(env: Env) -> None:
    """Read but never echoed: it went with the stopped turn, so Nest keeps it."""
    env.provider.script(until_interrupted())
    session_id = await running(env)
    await env.manager.send(session_id, "later", [])
    (run,) = env.provider.runs
    run.steered.clear()

    await env.manager.interrupt(session_id)
    await env.reach(session_id, SessionState.INTERRUPTED)

    assert [(m.text, m.sent) for m in await env.manager.queued(session_id)] == [("later", False)]


async def test_a_message_read_in_a_failed_turn_waits_again(env: Env) -> None:
    gate = asyncio.Event()
    env.provider.script(gated(gate, engine_error("overloaded")))
    session_id = await running(env)
    await env.manager.send(session_id, "later", [])
    (run,) = env.provider.runs
    run.steered.clear()

    gate.set()
    await env.reach(session_id, SessionState.FAILED)

    assert [(m.text, m.sent) for m in await env.manager.queued(session_id)] == [("later", False)]


async def test_a_pending_message_is_removed_until_the_agent_reads_it(env: Env) -> None:
    env.provider.script(until_interrupted())
    session_id = await running(env)
    removed = await env.manager.send(session_id, "never mind", [])
    kept = await env.manager.send(session_id, "this one stays", [])
    assert removed.queued_message is not None
    assert kept.queued_message is not None
    (run,) = env.provider.runs

    await env.manager.cancel_queued(session_id, removed.queued_message.id)
    run.steered.clear()  # the agent reads the other one
    with pytest.raises(MessageTakenError, match="already read"):
        await env.manager.cancel_queued(session_id, kept.queued_message.id)

    assert ("withdraw", removed.queued_message.id) in run.calls
    assert [m.text for m in await env.manager.queued(session_id)] == ["this one stays"]
    with pytest.raises(QueuedMessageNotFoundError):
        await env.manager.cancel_queued(session_id, removed.queued_message.id)


async def test_a_waiting_message_is_removed_without_asking_the_agent(env: Env) -> None:
    env.provider.script(until_interrupted())
    session_id = await running(env)
    sent = await env.manager.send(session_id, "later", [])
    assert sent.queued_message is not None
    await env.manager.interrupt(session_id)
    await env.reach(session_id, SessionState.INTERRUPTED)
    (run,) = env.provider.runs
    calls = len(run.calls)

    await env.manager.cancel_queued(session_id, sent.queued_message.id)

    assert run.calls[calls:] == []
    assert await env.manager.queued(session_id) == []


async def test_a_daemon_restart_keeps_pending_messages_waiting(env: Env) -> None:
    env.provider.script(until_interrupted())
    session_id = await running(env)
    await env.manager.send(session_id, "later", [])

    await env.manager.shutdown()
    restarted = env.build(timedelta(hours=1))
    await env.db.execute("UPDATE queued_messages SET sent = 1")  # as after a hard kill
    await restarted.recover()

    assert [(m.text, m.sent) for m in await restarted.queued(session_id)] == [("later", False)]
    assert (await env.store.get(session_id)).state is SessionState.INTERRUPTED
    await restarted.shutdown()


async def test_a_crash_leaves_messages_written_into_its_turn_waiting(env: Env) -> None:
    gate = asyncio.Event()
    env.provider.script(gated(gate, crash("the agent process ended")))
    session_id = await running(env)
    await env.manager.send(session_id, "later", [])

    gate.set()
    await env.reach(session_id, SessionState.FAILED)

    assert [(m.text, m.sent) for m in await env.manager.queued(session_id)] == [("later", False)]


async def test_a_message_with_a_new_file_waits_for_the_turn_to_end(env: Env) -> None:
    """Its folder needs a new run, which only the next turn opens."""
    gate = asyncio.Event()
    env.provider.script(gated(gate, reply("first done")), reply("read it"), reply("third"))
    session_id = await running(env)
    doc = await env.attachments.save("notes.txt", b"hi", "text/plain")

    with_file = await env.manager.send(session_id, "read this", [doc.id])
    after = await env.manager.send(session_id, "and this", [])
    gate.set()
    await idle_after(env, session_id, 3)

    assert with_file.queued_message is not None
    assert with_file.queued_message.sent is False
    # Messages keep their order: the next one waits too.
    assert after.queued_message is not None
    assert after.queued_message.sent is False
    inputs = [i.text for run in env.provider.runs for i in run.inputs]
    assert inputs == ["first", "read this", "and this"]
    assert not any(name == "steer" for name, _ in env.provider.runs[0].calls)


async def test_messages_wait_while_the_work_is_published(env: Env) -> None:
    gate = asyncio.Event()
    env.provider.script(gated(gate, reply("first done")), reply("second done"))
    session_id = await running(env)

    async with env.manager.publishing(session_id):
        sent = await env.manager.send(session_id, "second", [])
    gate.set()
    await idle_after(env, session_id, 2)

    assert sent.queued_message is not None
    assert sent.queued_message.sent is False


async def test_a_message_that_cannot_be_written_waits_for_the_next_turn(env: Env) -> None:
    gate = asyncio.Event()
    env.provider.script(gated(gate, reply("first done")), reply("second done"))
    session_id = await running(env)
    env.provider.steer_error = OSError("broken pipe")

    sent = await env.manager.send(session_id, "second", [])
    gate.set()
    await idle_after(env, session_id, 2)

    assert sent.queued_message is not None
    assert sent.queued_message.sent is False
    assert [i.text for i in env.provider.runs[0].inputs] == ["first", "second"]


async def test_messages_sent_while_the_worktree_is_made_go_into_the_first_turn(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    started, release = gate_worktree_add(monkeypatch)
    gate = asyncio.Event()
    env.provider.script(gated(gate, reads_then("all done")))
    created = await env.create(prompt="first", mode="worktree")
    await started.wait()

    sent = await env.manager.send(created.id, "also this", [])
    release.set()
    await until(lambda: bool(env.provider.runs) and bool(env.provider.runs[0].steered))
    gate.set()
    await idle_after(env, created.id, 1)

    assert sent.queued_message is not None
    assert sent.queued_message.sent is False
    assert await transcript(env, created.id) == [
        "user: first",
        "agent: working",
        "user: also this",
        "agent: all done",
    ]


async def test_send_now_on_a_resting_chat_starts_the_message(env: Env) -> None:
    env.provider.script(until_interrupted(), reply("second done"))
    session_id = await running(env)
    held = await env.manager.send(session_id, "held", [])
    assert held.queued_message is not None
    await env.manager.interrupt(session_id)
    await env.reach(session_id, SessionState.INTERRUPTED)

    await env.manager.send_now(session_id, held.queued_message.id)
    await idle_after(env, session_id, 2)

    assert [i.text for i in env.provider.runs[0].inputs] == ["first", "held"]
    assert await env.manager.queued(session_id) == []


async def test_send_now_while_the_work_is_published_puts_the_message_first(env: Env) -> None:
    env.provider.script(until_interrupted(), reply("one"), reply("two"))
    session_id = await running(env)
    first = await env.manager.send(session_id, "one", [])
    second = await env.manager.send(session_id, "two", [])
    assert first.queued_message is not None
    assert second.queued_message is not None
    await env.manager.interrupt(session_id)
    await env.reach(session_id, SessionState.INTERRUPTED)

    async with env.manager.publishing(session_id):
        await env.manager.send_now(session_id, second.queued_message.id)
        assert not env.manager.busy(session_id)

    assert [m.text for m in await env.manager.queued(session_id)] == ["two", "one"]


async def test_send_now_of_an_unknown_message_is_refused(env: Env) -> None:
    env.provider.script(reply("done"))
    created = await env.create(mode="in_place")
    await env.reach(created.id, SessionState.IDLE)

    with pytest.raises(QueuedMessageNotFoundError):
        await env.manager.send_now(created.id, "nope")


async def test_stop_on_a_resting_chat_is_still_refused(env: Env) -> None:
    env.provider.script(reply("done"))
    created = await env.create(mode="in_place")
    await env.reach(created.id, SessionState.IDLE)

    with pytest.raises(NoTurnInProgressError):
        await env.manager.interrupt(created.id)


async def test_an_echo_of_a_message_no_longer_queued_is_ignored(env: Env) -> None:
    gate = asyncio.Event()

    async def turn(run: FakeRun) -> None:
        await gate.wait()
        await run.sink.message_taken("gone", "cp-gone")
        await run.sink.result(RESULT)

    env.provider.script(turn)
    session_id = await running(env)
    gate.set()
    await idle_after(env, session_id, 1)

    assert await transcript(env, session_id) == ["user: first"]


@pytest.mark.parametrize("problem", ["new file", "broken pipe"])
async def test_a_waiting_message_that_cannot_go_into_the_first_turn_waits_for_its_end(
    env: Env, monkeypatch: pytest.MonkeyPatch, problem: str
) -> None:
    started, release = gate_worktree_add(monkeypatch)
    gate = asyncio.Event()
    env.provider.script(gated(gate, reply("first done")), reply("then this"))
    created = await env.create(prompt="first", mode="worktree")
    await started.wait()
    if problem == "new file":
        doc = await env.attachments.save("notes.txt", b"hi", "text/plain")
        await env.manager.send(created.id, "and this", [doc.id])
    else:
        await env.manager.send(created.id, "and this", [])
        env.provider.steer_error = OSError("broken pipe")

    release.set()
    await env.reach(created.id, SessionState.RUNNING)
    await until(lambda: env.manager._live[created.id].task is None)  # pyright: ignore[reportPrivateUsage]
    # Writing it into the turn is tried after the turn's task ends: wait for the failure
    # to be handled, so the message is back to waiting for the turn's end.
    failures = 0 if problem == "new file" else 1
    await until(lambda: env.provider.steer_failures == failures)
    pending: list[QueuedMessage] = []

    async def settled() -> bool:
        pending[:] = await env.manager.queued(created.id)
        return not any(m.sent for m in pending)

    await until(settled)
    env.provider.steer_error = None
    gate.set()
    await idle_after(env, created.id, 2)

    assert [(m.text, m.sent) for m in pending] == [("and this", False)]
    inputs = [i.text for run in env.provider.runs for i in run.inputs]
    assert inputs == ["first", "and this"]


async def test_a_failure_to_take_messages_back_still_ends_the_turn(
    env: Env, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    gate = asyncio.Event()
    env.provider.script(gated(gate, reply("first done")))
    session_id = await running(env)

    async def broken(session_id: str) -> list[str]:
        raise OSError("database is locked")

    monkeypatch.setattr(env.queue, "sent_ids", broken)
    gate.set()
    await env.reach(session_id, SessionState.IDLE)

    assert f"taking back the messages of session {session_id} failed" in caplog.text


async def test_stop_on_a_chat_this_process_never_ran_is_refused(env: Env) -> None:
    env.provider.script(reply("done"))
    created = await env.create(mode="in_place")
    await env.reach(created.id, SessionState.IDLE)
    restarted = env.build(timedelta(hours=1))

    with pytest.raises(NoTurnInProgressError):
        await restarted.interrupt(created.id)


async def test_messages_held_by_a_stop_go_into_the_next_turn(env: Env) -> None:
    gate = asyncio.Event()
    env.provider.script(until_interrupted(), gated(gate, reads_then("both done")))
    session_id = await running(env)
    await env.manager.send(session_id, "held", [])
    await env.manager.interrupt(session_id)
    await env.reach(session_id, SessionState.INTERRUPTED)

    await env.manager.send(session_id, "new", [])
    await until(lambda: bool(env.provider.runs[0].steered))
    gate.set()
    await idle_after(env, session_id, 2)

    assert [i.text for i in env.provider.runs[0].inputs] == ["first", "new"]
    assert await transcript(env, session_id) == [
        "user: first",
        "user: new",
        "agent: working",
        "user: held",
        "agent: both done",
    ]


# How Claude Code ends a turn when a message written into it arrived as the turn ended: it
# had the message but never answered it.
EDE = "[ede_diagnostic] result_type=user last_content_type=n/a stop_reason=tool_use"


@pytest.mark.parametrize("read", [True, False])
async def test_a_turn_claude_code_ends_holding_a_written_message_hands_off_to_it(
    env: Env, read: bool
) -> None:
    gate = asyncio.Event()
    env.provider.script(gated(gate, engine_error(EDE)), reply("done, pineapple"))
    session_id = await running(env)
    await env.manager.send(session_id, "also end in pineapple", [])
    (run,) = env.provider.runs
    if read:
        run.steered.clear()  # read, never echoed

    gate.set()
    await idle_after(env, session_id, 2)

    # No failure: the message goes straight on as the next turn.
    assert await env.states(session_id) == ["starting", "running", "running", "idle"]
    assert [i.text for i in run.inputs] == ["first", "also end in pineapple"]
    assert await transcript(env, session_id) == [
        "user: first",
        "agent: working",
        "user: also end in pineapple",
        "agent: done, pineapple",
    ]
    (ended, done) = await results(env, session_id)
    assert ended["handoff"] is True
    assert ended["errors"] == [EDE]
    assert "handoff" not in done
    assert await env.manager.queued(session_id) == []


async def test_the_same_engine_error_without_a_written_message_fails_the_turn(env: Env) -> None:
    env.provider.script(engine_error(EDE))
    session_id = (await env.create(prompt="first", mode="in_place")).id

    await env.reach(session_id, SessionState.FAILED)

    assert await env.states(session_id) == ["starting", "running", "failed"]
    (ended,) = await results(env, session_id)
    assert "handoff" not in ended
    assert "stopped" not in ended


async def test_another_engine_error_with_a_written_message_still_fails(env: Env) -> None:
    gate = asyncio.Event()
    env.provider.script(gated(gate, engine_error("[ede_diagnostic] result_type=assistant")))
    session_id = await running(env)
    await env.manager.send(session_id, "later", [])

    gate.set()
    await env.reach(session_id, SessionState.FAILED)

    assert [(m.text, m.sent) for m in await env.manager.queued(session_id)] == [("later", False)]
    (ended,) = await results(env, session_id)
    assert "handoff" not in ended
