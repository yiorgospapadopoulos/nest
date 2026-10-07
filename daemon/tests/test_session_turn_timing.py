"""Turn boundaries clients time the chat by: the turn start mark and the turn duration (D045)."""

import asyncio
from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path

import pytest
from pydantic import JsonValue

from harness.config.models import WorktreeConfig
from harness.events import types
from harness.sessions.models import SessionState
from harness.storage.db import Database
from tests.async_support import until
from tests.fake_provider import FakeRun, Turn, crash, hang, reply, until_interrupted
from tests.fakes import FakeClock
from tests.session_support import Env


@pytest.fixture
async def env(tmp_path: Path, db: Database, clock: FakeClock) -> AsyncIterator[Env]:
    environment = Env(tmp_path, db, clock)
    await environment.register()
    yield environment
    await environment.manager.shutdown()


def taking(env: Env, seconds: float, then: Turn) -> Turn:
    """A turn during which the clock moves on by `seconds`."""

    async def turn(run: FakeRun) -> None:
        env.clock.advance(timedelta(seconds=seconds))
        await then(run)

    return turn


async def state_payloads(env: Env, session_id: str) -> list[dict[str, JsonValue]]:
    return [
        event.payload
        for event in await env.bus.session_events(session_id)
        if event.type == types.SESSION_STATE
    ]


async def test_a_turn_marks_its_start_and_ends_with_its_duration(env: Env) -> None:
    env.provider.script(taking(env, 72.4, reply("done")))
    created = await env.create()
    await env.reach(created.id, SessionState.IDLE)

    events = await env.bus.session_events(created.id)
    start = next(e for e in events if e.payload.get("turn_start") is True)
    assert await state_payloads(env, created.id) == [
        {"state": "starting", "error": None},
        {"state": "running", "error": None, "turn_start": True},
        {"state": "idle", "error": None, "duration_ms": 72400},
    ]
    assert events[-1].ts - start.ts == timedelta(seconds=72.4)


async def test_a_turn_the_agent_starts_on_its_own_is_timed_too(env: Env) -> None:
    env.provider.script(reply("first"))
    created = await env.create()
    await env.reach(created.id, SessionState.IDLE)

    async def unprompted(run: FakeRun) -> None:
        # The turn starts with the agent's first output, when nothing has been sent.
        env.clock.advance(timedelta(seconds=50))
        await run.sink.text_delta("A background task finished")
        await taking(env, 3, reply("Here is what it found"))(run)

    env.provider.runs[0].emit(unprompted)
    await until(lambda: _count(env, created.id, 5))

    assert (await state_payloads(env, created.id))[-2:] == [
        {"state": "running", "error": None, "turn_start": True},
        {"state": "idle", "error": None, "duration_ms": 3000},
    ]


async def test_queued_messages_start_new_turns_without_ending_in_a_state(env: Env) -> None:
    gate = asyncio.Event()

    async def slow(run: FakeRun) -> None:
        await gate.wait()
        await reply("first done")(run)

    env.provider.script(slow, taking(env, 2, reply("second done")))
    created = await env.create(prompt="first")
    await env.reach(created.id, SessionState.RUNNING)
    await env.manager.send(created.id, "second", [])
    env.clock.advance(timedelta(seconds=9))
    gate.set()
    await until(lambda: _count(env, created.id, 4))

    assert await state_payloads(env, created.id) == [
        {"state": "starting", "error": None},
        {"state": "running", "error": None, "turn_start": True},
        {"state": "running", "error": None, "turn_start": True},
        # Measured from the second turn's own start.
        {"state": "idle", "error": None, "duration_ms": 2000},
    ]


async def test_an_interrupted_turn_reports_how_long_it_ran(env: Env) -> None:
    env.provider.script(until_interrupted())
    created = await env.create()
    await env.reach(created.id, SessionState.RUNNING)
    env.clock.advance(timedelta(seconds=40))

    await env.manager.interrupt(created.id)
    await env.reach(created.id, SessionState.INTERRUPTED)

    assert (await state_payloads(env, created.id))[-1] == {
        "state": "interrupted",
        "error": None,
        "duration_ms": 40000,
    }


async def test_a_turn_stopped_before_the_agent_ran_has_no_duration(env: Env) -> None:
    env.repos.update_worktree_config("repo", WorktreeConfig(setup=["exit 7"]))
    created = await env.create()

    await env.reach(created.id, SessionState.FAILED)

    payload = (await state_payloads(env, created.id))[-1]
    assert (payload["state"], payload["duration_ms"]) == ("failed", None)


async def test_a_failed_turn_reports_how_long_it_ran(env: Env) -> None:
    env.provider.script(taking(env, 5, crash("gone")))
    created = await env.create()

    await env.reach(created.id, SessionState.FAILED)

    payload = (await state_payloads(env, created.id))[-1]
    assert (payload["state"], payload["duration_ms"]) == ("failed", 5000)


async def test_a_turn_cut_off_by_shutdown_reports_how_long_it_ran(env: Env) -> None:
    env.provider.script(hang())
    created = await env.create()
    await env.reach(created.id, SessionState.RUNNING)
    env.clock.advance(timedelta(minutes=2))

    await env.manager.shutdown()

    assert (await state_payloads(env, created.id))[-1] == {
        "state": "interrupted",
        "error": None,
        "duration_ms": 120000,
    }


async def _count(env: Env, session_id: str, states: int) -> bool:
    return len(await state_payloads(env, session_id)) >= states
