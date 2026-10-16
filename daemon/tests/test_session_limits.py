"""Chats paused at the usage limit go on by themselves after the reset (B78)."""

import asyncio
from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path

import pytest
from pydantic import JsonValue

from nestd.events import types
from nestd.providers.base import LimitHit, UsageInfo, UsageWindow
from nestd.sessions.errors import NotPausedError
from nestd.sessions.limits import RESUME_MARGIN, UNKNOWN_RESET_DELAY
from nestd.sessions.manager import CONTINUE_TEXT
from nestd.sessions.models import LimitPause, Session, SessionState, UpdateSession
from nestd.storage.db import Database
from tests.async_support import until
from tests.fake_provider import (
    RESETS,
    FakeRun,
    Turn,
    cut_off,
    engine_error,
    limited,
    limits,
    reply,
    until_interrupted,
)
from tests.fakes import START, FakeClock
from tests.session_support import Env

RESUMES = RESETS + RESUME_MARGIN


@pytest.fixture
async def env(tmp_path: Path, db: Database, clock: FakeClock) -> AsyncIterator[Env]:
    environment = Env(tmp_path, db, clock)
    await environment.register()
    yield environment
    await environment.manager.shutdown()


async def paused_chat(env: Env, *turns: Turn, prompt: str = "first") -> Session:
    """A chat whose first turn the usage limit cut off; `turns` follow."""
    env.provider.script(limited(), *turns)
    created = await env.create(prompt=prompt, mode="in_place")
    return await env.reach(created.id, SessionState.IDLE)


async def payloads(env: Env, session_id: str, event_type: str) -> list[dict[str, JsonValue]]:
    return [
        event.payload
        for event in await env.bus.session_events(session_id)
        if event.type == event_type
    ]


async def user_messages(env: Env, session_id: str) -> list[tuple[object, object]]:
    return [
        (payload["text"], payload["origin"])
        for payload in await payloads(env, session_id, types.SESSION_USER_MESSAGE)
    ]


async def queued_texts(env: Env, session_id: str) -> list[str]:
    return [message.text for message in await env.manager.queued(session_id)]


async def results(env: Env, session_id: str, count: int) -> None:
    async def done() -> bool:
        return len(await payloads(env, session_id, types.SESSION_RESULT)) >= count

    await until(done)


async def settled(env: Env, session_id: str, count: int) -> Session:
    """The chat after `count` turn results, once it is idle again."""
    await results(env, session_id, count)
    return await env.reach(session_id, SessionState.IDLE)


async def reset(env: Env) -> None:
    env.clock.current = RESUMES
    await env.manager.tick_limits()


async def test_a_turn_the_limit_cuts_off_pauses_the_chat_instead_of_failing(env: Env) -> None:
    session = await paused_chat(env)

    assert session.state is SessionState.IDLE
    assert session.last_error is None
    pause = LimitPause(window="five_hour", resets_at=RESETS, resume_at=RESUMES, since=START)
    assert session.limit_pause == pause
    (paused,) = await payloads(env, session.id, types.SESSION_LIMIT_PAUSED)
    assert paused == {"limit_pause": pause.model_dump(mode="json")}
    (updated,) = await payloads(env, session.id, types.SESSION_UPDATED)
    assert updated["changes"] == {"limit_pause": pause.model_dump(mode="json")}
    (result,) = await payloads(env, session.id, types.SESSION_RESULT)
    assert (result["limit"], result["is_error"]) == (True, True)
    ended = [p for p in await payloads(env, session.id, types.SESSION_STATE) if "duration_ms" in p]
    assert [(p["state"], p["error"]) for p in ended] == [("idle", None)]
    (run,) = env.provider.runs
    assert not run.closed


async def test_a_message_cut_off_with_no_reset_named_pauses_for_a_fixed_delay(env: Env) -> None:
    env.provider.script(cut_off())
    created = await env.create(mode="in_place")
    session = await env.reach(created.id, SessionState.IDLE)

    assert session.limit_pause == LimitPause(
        window=None, resets_at=None, resume_at=START + UNKNOWN_RESET_DELAY, since=START
    )


async def test_a_reset_already_past_goes_on_after_the_margin(env: Env) -> None:
    env.provider.script(limited(resets_at=START - timedelta(minutes=1)))
    created = await env.create(mode="in_place")
    session = await env.reach(created.id, SessionState.IDLE)

    assert session.limit_pause is not None
    assert session.limit_pause.resume_at == START + RESUME_MARGIN


async def test_a_limit_reported_in_a_turn_that_finished_normally_does_not_pause(
    env: Env,
) -> None:
    async def warned(run: FakeRun) -> None:
        await run.sink.limit_hit(LimitHit(window="five_hour", resets_at=RESETS))
        await reply("done")(run)

    env.provider.script(warned, reply("again"))
    created = await env.create(mode="in_place")
    session = await env.reach(created.id, SessionState.IDLE)
    await env.manager.send(created.id, "more", [])
    await settled(env, created.id, 2)

    assert session.limit_pause is None
    assert await payloads(env, created.id, types.SESSION_LIMIT_PAUSED) == []


async def test_a_failure_without_a_limit_report_still_fails(env: Env) -> None:
    """Usage reports, even of a full window, are no limit report: the turn fails as before."""
    full = UsageInfo(five_hour=UsageWindow(utilization=1.0, resets_at=RESETS), seven_day=None)
    env.provider.script(limits(full, engine_error("API Error: 500")))
    created = await env.create(mode="in_place")
    session = await env.reach(created.id, SessionState.FAILED)

    assert (session.last_error, session.limit_pause) == ("API Error: 500", None)


async def test_a_habit_runs_turn_cut_off_by_the_limit_fails(env: Env) -> None:
    """Habit runs are not paused (B78): the run ends, as before."""
    env.provider.script(reply("ok"), limited())
    created = await env.create(mode="in_place")
    await env.reach(created.id, SessionState.IDLE)
    await env.store.update(created.id, habit_run_id="run-1")

    await env.manager.send(created.id, "again", [])
    session = await env.reach(created.id, SessionState.FAILED)

    assert (session.last_error, session.limit_pause) == ("limit reached", None)


async def test_messages_wait_while_paused_and_nothing_starts(env: Env) -> None:
    gate = asyncio.Event()

    async def slow_limit(run: FakeRun) -> None:
        await gate.wait()
        await limited()(run)

    env.provider.script(slow_limit)
    created = await env.create(prompt="first", mode="in_place")
    await env.reach(created.id, SessionState.RUNNING)
    during = await env.manager.send(created.id, "during", [])
    gate.set()
    await env.reach(created.id, SessionState.IDLE)
    after = await env.manager.send(created.id, "after", [])
    async with env.manager.publishing(created.id):
        pass
    env.clock.current = RESUMES - timedelta(seconds=1)
    await env.manager.tick_limits()

    assert during.queued_message is not None
    assert after.queued_message is not None
    assert await queued_texts(env, created.id) == ["during", "after"]
    (run,) = env.provider.runs
    assert len(run.inputs) == 1
    assert (await env.store.get(created.id)).limit_pause is not None


async def test_after_the_reset_the_queued_messages_go_on_in_order(env: Env) -> None:
    session = await paused_chat(env, reply("second done"), reply("third done"))
    await env.manager.send(session.id, "second", [])
    await env.manager.send(session.id, "third", [])

    await reset(env)
    done = await settled(env, session.id, 3)

    assert await user_messages(env, session.id) == [
        ("first", None),
        ("second", None),
        ("third", None),
    ]
    (run,) = env.provider.runs
    assert [user_input.text for user_input in run.inputs] == ["first", "second", "third"]
    assert done.limit_pause is None
    assert await payloads(env, session.id, types.SESSION_LIMIT_CLEARED) == [{"reason": "reset"}]
    assert await queued_texts(env, session.id) == []


async def test_with_nothing_queued_the_chat_is_told_to_continue(env: Env) -> None:
    session = await paused_chat(env, reply("picked up"))

    await reset(env)
    await settled(env, session.id, 2)

    assert await user_messages(env, session.id) == [
        ("first", None),
        (CONTINUE_TEXT, "limit_resume"),
    ]
    (run,) = env.provider.runs
    assert run.inputs[-1].text == CONTINUE_TEXT


async def test_a_limit_that_still_holds_pauses_the_chat_again(env: Env) -> None:
    later = RESETS + timedelta(hours=5)
    session = await paused_chat(env, limited(resets_at=later, window="seven_day"))

    await reset(env)
    await results(env, session.id, 2)
    again = await env.reach(session.id, SessionState.IDLE)

    assert again.limit_pause == LimitPause(
        window="seven_day", resets_at=later, resume_at=later + RESUME_MARGIN, since=RESUMES
    )
    assert len(await payloads(env, session.id, types.SESSION_LIMIT_PAUSED)) == 2


async def test_resume_now_goes_on_at_once(env: Env) -> None:
    session = await paused_chat(env, reply("second done"))
    await env.manager.send(session.id, "second", [])

    resumed = await env.manager.resume_limit(session.id)
    done = await settled(env, session.id, 2)

    assert resumed.limit_pause is None
    assert await user_messages(env, session.id) == [("first", None), ("second", None)]
    assert await payloads(env, session.id, types.SESSION_LIMIT_CLEARED) == [{"reason": "resumed"}]
    assert done.limit_pause is None
    # The reset time passing later changes nothing.
    await reset(env)
    assert len(await payloads(env, session.id, types.SESSION_USER_MESSAGE)) == 2


async def test_resume_now_is_refused_for_a_chat_that_is_not_paused(env: Env) -> None:
    env.provider.script(reply("done"))
    created = await env.create(mode="in_place")
    await env.reach(created.id, SessionState.IDLE)

    with pytest.raises(NotPausedError) as refused:
        await env.manager.resume_limit(created.id)

    assert refused.value.status_code == 409
    assert refused.value.payload()["code"] == "not_paused"


async def test_send_now_while_paused_ends_the_pause_and_sends(env: Env) -> None:
    session = await paused_chat(env, reply("urgent done"))
    queued = (await env.manager.send(session.id, "urgent", [])).queued_message
    assert queued is not None

    await env.manager.send_now(session.id, queued.id)
    done = await settled(env, session.id, 2)

    assert await user_messages(env, session.id) == [("first", None), ("urgent", None)]
    assert done.limit_pause is None
    assert await payloads(env, session.id, types.SESSION_LIMIT_CLEARED) == [{"reason": "resumed"}]


async def test_stop_while_paused_ends_the_pause_without_sending(env: Env) -> None:
    session = await paused_chat(env)
    await env.manager.send(session.id, "later", [])

    await env.manager.interrupt(session.id)
    stopped = await env.reach(session.id, SessionState.INTERRUPTED)
    await reset(env)
    async with env.manager.publishing(session.id):
        pass

    assert stopped.limit_pause is None
    assert await payloads(env, session.id, types.SESSION_LIMIT_CLEARED) == [{"reason": "stopped"}]
    assert await queued_texts(env, session.id) == ["later"]
    (run,) = env.provider.runs
    assert len(run.inputs) == 1


async def test_closing_cancels_the_pause(env: Env) -> None:
    session = await paused_chat(env)

    closed = await env.manager.close(session.id, remove_worktree=False)
    await reset(env)

    assert closed.state is SessionState.CLOSED
    assert closed.limit_pause is None
    assert await payloads(env, session.id, types.SESSION_LIMIT_CLEARED) == [{"reason": "closed"}]
    (run,) = env.provider.runs
    assert len(run.inputs) == 1


async def test_deleting_cancels_the_pause(env: Env) -> None:
    session = await paused_chat(env)

    await env.manager.purge(session.id)
    await reset(env)

    assert await env.store.list_sessions() == []
    (run,) = env.provider.runs
    assert len(run.inputs) == 1


async def test_archiving_cancels_the_pause(env: Env) -> None:
    session = await paused_chat(env)

    await env.manager.update(session.id, UpdateSession(archived=True))
    archived = await env.reach(session.id, SessionState.INTERRUPTED)
    await reset(env)

    assert archived.limit_pause is None
    assert await payloads(env, session.id, types.SESSION_LIMIT_CLEARED) == [{"reason": "archived"}]
    assert len(env.provider.runs[0].inputs) == 1


async def restarted(env: Env) -> None:
    """The daemon stops and starts again on the same database."""
    await env.manager.shutdown()
    env.manager = env.build(timedelta(hours=1))
    await env.manager.recover()


async def test_after_a_restart_a_pause_already_over_goes_on_at_once(env: Env) -> None:
    session = await paused_chat(env, reply("picked up"))
    await env.manager.send(session.id, "queued", [])
    await restarted(env)
    env.clock.current = RESUMES + timedelta(hours=1)

    await env.manager.start(tick=timedelta(hours=1))
    done = await settled(env, session.id, 2)

    assert await user_messages(env, session.id) == [("first", None), ("queued", None)]
    assert done.limit_pause is None
    assert [user_input.text for user_input in env.provider.runs[1].inputs] == ["queued"]


async def test_after_a_restart_a_pause_still_running_goes_on_at_its_time(env: Env) -> None:
    session = await paused_chat(env, reply("picked up"))
    await restarted(env)

    await env.manager.start(tick=timedelta(hours=1))
    await env.manager.tick_limits()
    waiting = await env.store.get(session.id)
    await reset(env)
    await settled(env, session.id, 2)

    assert waiting.limit_pause is not None
    assert await user_messages(env, session.id) == [
        ("first", None),
        (CONTINUE_TEXT, "limit_resume"),
    ]


async def test_stop_after_a_restart_ends_the_pause(env: Env) -> None:
    session = await paused_chat(env)
    await restarted(env)

    await env.manager.interrupt(session.id)
    stopped = await env.reach(session.id, SessionState.INTERRUPTED)

    assert stopped.limit_pause is None


async def test_a_chat_open_in_claude_code_at_the_reset_is_left_to_it(env: Env) -> None:
    session = await paused_chat(env)
    env.claude.open_chat(4242, "sdk-1")
    env.alive.add(4242)

    await reset(env)

    assert (await env.store.get(session.id)).limit_pause is None
    assert await payloads(env, session.id, types.SESSION_LIMIT_CLEARED) == [{"reason": "reset"}]
    assert len(env.provider.runs[0].inputs) == 1


async def test_a_turn_the_agent_starts_while_paused_takes_the_queue_after_the_reset(
    env: Env,
) -> None:
    session = await paused_chat(env, reply("queued done"))
    await env.manager.send(session.id, "queued", [])
    (run,) = env.provider.runs
    gate = asyncio.Event()

    async def own(run: FakeRun) -> None:
        await run.sink.text_delta("a background task finished")
        await gate.wait()
        await reply("noted")(run)

    run.emit(own)
    await env.reach(session.id, SessionState.RUNNING)
    await reset(env)
    gate.set()
    await settled(env, session.id, 3)

    assert await user_messages(env, session.id) == [("first", None), ("queued", None)]


async def test_stop_while_paused_also_stops_a_turn_the_agent_started(env: Env) -> None:
    session = await paused_chat(env)
    (run,) = env.provider.runs
    run.emit(until_interrupted())
    await env.reach(session.id, SessionState.RUNNING)

    await env.manager.interrupt(session.id)
    stopped = await env.reach(session.id, SessionState.INTERRUPTED)

    assert stopped.limit_pause is None
    assert ("interrupt", None) in run.calls
    interrupted = [
        p
        for p in await payloads(env, session.id, types.SESSION_STATE)
        if p["state"] == "interrupted"
    ]
    assert len(interrupted) == 1
