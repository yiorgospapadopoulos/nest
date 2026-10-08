"""Moments where two things happen to a session at once (B31: BUG-02, BUG-12 to BUG-19)."""

import asyncio
from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path

import pytest

from harness.attachments.store import Attachment
from harness.events import types
from harness.sessions.models import SessionState
from harness.storage.db import Database
from tests.async_support import until
from tests.fake_provider import FakeRun, background, reply
from tests.fakes import FakeClock
from tests.session_support import Env


@pytest.fixture
async def env(tmp_path: Path, db: Database, clock: FakeClock) -> AsyncIterator[Env]:
    environment = Env(tmp_path, db, clock)
    await environment.register()
    yield environment
    await environment.manager.shutdown()


async def user_messages(env: Env, session_id: str) -> list[object]:
    return [
        event.payload["text"]
        for event in await env.bus.session_events(session_id)
        if event.type == types.SESSION_USER_MESSAGE
    ]


def texts(run: FakeRun) -> list[str]:
    return [user_input.text for user_input in run.inputs]


async def test_stop_as_a_queued_message_starts_keeps_it_from_the_agent(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """BUG-12: Stop pressed while the next queued message is on its way to the agent."""
    release_first = asyncio.Event()

    async def first_turn(run: FakeRun) -> None:
        await release_first.wait()
        await reply("first done")(run)

    env.provider.script(reply("prompt done"), first_turn, reply("second done"))
    created = await env.create(mode="in_place", allow_dirty=True)
    await env.reach(created.id, SessionState.IDLE)
    await env.manager.send(created.id, "message A", [])
    await env.reach(created.id, SessionState.RUNNING)
    await env.manager.send(created.id, "message B", [])
    in_gap, leave_gap = asyncio.Event(), asyncio.Event()
    original = env.attachments.for_session

    async def slow_for_session(ids: list[str], session_id: str | None) -> list[Attachment]:
        in_gap.set()
        await leave_gap.wait()
        return await original(ids, session_id)

    monkeypatch.setattr(env.attachments, "for_session", slow_for_session)
    release_first.set()
    await asyncio.wait_for(in_gap.wait(), 5)

    await env.manager.interrupt(created.id)
    leave_gap.set()
    await env.reach(created.id, SessionState.INTERRUPTED)

    (run,) = env.provider.runs
    assert texts(run) == ["Fix the bug\nDetails here", "message A"]
    assert ("interrupt", None) not in run.calls
    # Shown like a message sent just before Stop, so it is not lost.
    assert await user_messages(env, created.id) == [
        "Fix the bug\nDetails here",
        "message A",
        "message B",
    ]
    assert await env.manager.queued(created.id) == []
    assert not env.manager.busy(created.id)


async def test_a_nudge_while_the_run_opens_starts_the_next_turn(env: Env) -> None:
    """BUG-13: the nudge interrupts the start and runs at once (D036)."""
    gate = asyncio.Event()
    env.provider.open_gate = gate
    env.provider.script(reply("answer to the nudge"))
    created = await env.create(mode="in_place", allow_dirty=True)
    await env.reach(created.id, SessionState.RUNNING)

    result = await env.manager.send(created.id, "You seem stuck", [], interrupt=True)
    env.provider.open_gate = None
    gate.set()
    await until(lambda: bool(env.provider.runs) and bool(env.provider.runs[0].inputs))
    await env.reach(created.id, SessionState.IDLE)

    assert result.queued_message is not None
    (run,) = env.provider.runs
    assert texts(run) == ["You seem stuck"]
    assert await env.manager.queued(created.id) == []
    assert await env.states(created.id) == ["starting", "running", "running", "idle"]


async def test_two_messages_at_the_same_moment_run_one_after_the_other(env: Env) -> None:
    """BUG-17: the second is queued, not refused (D032)."""
    env.provider.script(reply("prompt done"), reply("one"), reply("two"))
    created = await env.create(mode="in_place", allow_dirty=True)
    await env.reach(created.id, SessionState.IDLE)

    first, second = await asyncio.gather(
        env.manager.send(created.id, "first", []), env.manager.send(created.id, "second", [])
    )
    await until(lambda: len(env.provider.runs[0].inputs) == 3)
    await env.reach(created.id, SessionState.IDLE)

    assert (first.queued_message is None) != (second.queued_message is None)
    assert sorted(texts(env.provider.runs[0])[1:]) == ["first", "second"]


async def test_a_message_sent_as_the_idle_close_runs_waits_for_the_agent_to_exit(
    env: Env,
) -> None:
    """BUG-16: harness's own exiting process is not "open in Claude Code"."""
    env.manager = env.build(timedelta(milliseconds=20))
    env.provider.script(reply("done"), reply("again"))
    created = await env.create(mode="in_place", allow_dirty=True)
    await env.reach(created.id, SessionState.IDLE)
    (first,) = env.provider.runs
    exiting, exit_now = asyncio.Event(), asyncio.Event()
    real_close = first.close

    async def slow_close() -> None:
        exiting.set()
        await exit_now.wait()  # the CLI runs its SessionEnd hooks, then exits
        await real_close()

    first.close = slow_close  # type: ignore[method-assign]
    env.claude.open_chat(4242, "sdk-1", entrypoint="sdk-py")
    env.alive.add(4242)
    await asyncio.wait_for(exiting.wait(), 5)

    sent = await env.manager.send(created.id, "one more thing", [])
    await asyncio.sleep(0.05)
    opened_too_early = len(env.provider.runs) > 1
    exit_now.set()
    await until(lambda: len(env.provider.runs) == 2 and bool(env.provider.runs[1].inputs))
    await env.reach(created.id, SessionState.IDLE)

    assert sent.queued_message is None
    assert not opened_too_early
    assert first.closed
    assert texts(env.provider.runs[1]) == ["one more thing"]


async def test_a_turn_that_ends_before_its_message_is_sent_still_closes_its_idle_run(
    env: Env,
) -> None:
    """BUG-19: the idle close is scheduled once the sending task is done."""
    env.manager = env.build(timedelta(milliseconds=10))
    gate = asyncio.Event()
    env.provider.send_gate = gate
    env.provider.script(reply("fast"))
    created = await env.create(mode="in_place", allow_dirty=True)
    await env.reach(created.id, SessionState.IDLE)

    gate.set()

    await until(lambda: env.provider.runs[0].closed)


async def test_a_document_attached_while_background_tasks_run_keeps_the_run(env: Env) -> None:
    """BUG-02: a new attachment folder waits for the next run, as a new effort does (D046)."""
    env.provider.script(background(1, reply("started a background agent")), reply("read it"))
    created = await env.create(mode="in_place", allow_dirty=True)
    await env.reach(created.id, SessionState.IDLE)
    doc = await env.attachments.save("notes.txt", b"hi", "text/plain")

    await env.manager.send(created.id, "read this", [doc.id])
    await until(lambda: len(env.provider.runs[0].inputs) == 2)
    await env.reach(created.id, SessionState.IDLE)

    (run,) = env.provider.runs
    assert not run.closed
    assert run.inputs[1].file_paths == (doc.path,)
