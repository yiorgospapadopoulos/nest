"""The habit scheduler (B42): due runs, one at a time, lateness, the usage guard, how runs
end, history and restarts. The clock is fake: each check is a direct `tick()`.
"""

import asyncio
import logging
from datetime import timedelta

import pytest

from harness.approvals.models import ApprovalStatus
from harness.context import AppContext
from harness.events import types
from harness.pixies.habit_models import UpdateHabit
from harness.pixies.habit_store import KEEP_RUNS, StoredRun
from harness.pixies.prompt import HABIT_RUN_NOTE
from harness.pixies.scheduler import (
    INTERRUPTED_REASON,
    LATE_REASON,
    PAUSED_REASON,
    RESTARTED_REASON,
    STALLED_REASON,
    USAGE_REASON,
    HabitScheduler,
)
from harness.providers.base import UsageInfo, UsageWindow
from harness.sessions.models import Session, SessionState
from tests.async_support import until
from tests.fake_provider import (
    FakeProvider,
    FakeRun,
    ask,
    engine_error,
    hang,
    reply,
    until_interrupted,
)
from tests.fakes import FakeClock
from tests.habit_support import (
    ctx,
    ended,
    make_habit,
    make_pixie,
    provider,
    published,
    reporting,
    run_now,
    runs,
    session_of,
    started,
)

__all__ = ["ctx", "provider"]


async def test_nothing_runs_before_its_time(ctx: AppContext, clock: FakeClock) -> None:
    pixie = await make_pixie(ctx)
    habit = await make_habit(ctx, pixie.id, schedule={"kind": "daily", "time": "12:30"})

    await ctx.habit_scheduler.tick()

    assert await runs(ctx, habit) == []
    assert habit.next_due_at == clock.now() + timedelta(minutes=30)
    assert habit.last_run is None


async def test_a_scheduled_habit_runs_in_a_fresh_session_and_ends_quiet(
    ctx: AppContext, provider: FakeProvider, clock: FakeClock
) -> None:
    pixie = await make_pixie(ctx)
    habit = await make_habit(ctx, pixie.id, schedule={"kind": "daily", "time": "12:30"})
    provider.script(reply("Nothing worth reporting."))
    clock.advance(timedelta(minutes=30))

    await ctx.habit_scheduler.tick()
    [running] = await runs(ctx, habit)
    session = await session_of(ctx, running)
    await ended(ctx)
    [run] = await runs(ctx, habit)
    closed = await session_of(ctx, run)
    [agent] = provider.runs
    messages = [
        e.payload["text"]
        for e in await ctx.bus.session_events(session.id)
        if e.type == types.SESSION_USER_MESSAGE
    ]

    assert running.outcome == "running"
    assert (running.due_at, running.started_at) == (clock.now(), clock.now())
    assert (session.habit_run_id, session.pixie_id, session.title) == (
        running.id,
        pixie.id,
        "Check",
    )
    assert session.cwd == agent.spec.cwd
    assert agent.spec.resume_id is None
    assert (agent.spec.system_prompt_append or "").endswith(HABIT_RUN_NOTE)
    assert messages == ['Run your habit "Check":\nLook at CI.']
    assert (run.outcome, run.reason, run.ended_at) == ("quiet", None, clock.now())
    assert closed.state is SessionState.CLOSED
    # Not the pixie's chat, not in any project's list, and not announced as finished.
    assert (await ctx.pixies.get(pixie.id)).chat_session_id is None
    assert await ctx.sessions.list_sessions() == []
    assert await published(ctx, types.NOTIFY) == []
    habit_now = (await ctx.habits.list_habits(pixie.id))[0]
    assert habit_now.last_run is not None
    assert habit_now.last_run.model_dump() == run.model_dump()
    assert habit_now.next_due_at == clock.now() + timedelta(days=1)


async def test_run_events_follow_the_outcome(ctx: AppContext, provider: FakeProvider) -> None:
    pixie = await make_pixie(ctx)
    habit = await make_habit(ctx, pixie.id)
    provider.script(reply("ok"))

    run = await run_now(ctx, habit)

    updates = await published(ctx, types.HABIT_RUN_UPDATED)
    habits = await published(ctx, types.HABIT_UPDATED)

    assert [e["run"]["outcome"] for e in updates] == ["queued", "running", "quiet"]
    assert updates[-1]["run"] == run.model_dump(mode="json")
    assert set(updates[-1]["run"]) == {
        "id",
        "habit_id",
        "pixie_id",
        "session_id",
        "due_at",
        "started_at",
        "ended_at",
        "outcome",
        "reason",
        "report_title",
    }
    assert habits[-1]["habit"]["last_run"]["outcome"] == "quiet"


async def test_a_run_that_reports_is_reported(ctx: AppContext, provider: FakeProvider) -> None:
    pixie = await make_pixie(ctx)
    habit = await make_habit(ctx, pixie.id)
    provider.script(
        reporting(title="CI is red", then=reporting(title="Still red")),
        reply("Looking."),
    )

    run = await run_now(ctx, habit)

    assert (run.outcome, run.report_title) == ("reported", "CI is red")


async def test_one_run_at_a_time_in_due_order(
    ctx: AppContext, provider: FakeProvider, clock: FakeClock
) -> None:
    first = await make_pixie(ctx, "First")
    second = await make_pixie(ctx, "Second")
    later = await make_habit(ctx, first.id, schedule={"kind": "daily", "time": "12:30"})
    earlier = await make_habit(ctx, second.id, schedule={"kind": "hourly", "minute": 15})
    release = asyncio.Event()

    async def slow(run: FakeRun) -> None:
        await release.wait()
        await reply("done")(run)

    provider.script(slow, reply("done"))
    clock.advance(timedelta(minutes=30))

    await ctx.habit_scheduler.tick()
    [started] = await runs(ctx, earlier)
    [waiting] = await runs(ctx, later)
    await ctx.habit_scheduler.tick()
    still = (await runs(ctx, later))[0].outcome
    release.set()
    await until(lambda: ctx.habit_scheduler.current_run is None)
    await ctx.habit_scheduler.tick()
    await ended(ctx)

    assert started.outcome == "running"
    assert started.due_at == clock.now() - timedelta(minutes=15)
    assert (waiting.outcome, still) == ("queued", "queued")
    assert [r.outcome for r in await runs(ctx, earlier)] == ["quiet"]
    assert [r.outcome for r in await runs(ctx, later)] == ["quiet"]


async def test_a_run_past_its_minutes_times_out_and_a_late_scheduled_run_is_skipped(
    ctx: AppContext, provider: FakeProvider, clock: FakeClock
) -> None:
    pixie = await make_pixie(ctx)
    long = await make_habit(ctx, pixie.id, name="Long", max_minutes=120)
    daily = await make_habit(ctx, pixie.id, schedule={"kind": "daily", "time": "12:30"})
    provider.script(hang())
    await ctx.habits.run_now(pixie.id, long.id)
    await started(ctx, provider)
    clock.advance(timedelta(minutes=30))
    await ctx.habit_scheduler.tick()
    clock.advance(timedelta(minutes=89))
    await ctx.habit_scheduler.tick()
    running = (await runs(ctx, long))[0].outcome

    # 14:00: two hours in, the long run times out; the 12:30 run is 90 minutes late.
    provider.script(hang())
    clock.advance(timedelta(minutes=1))
    await started(ctx, provider)
    [timed_out] = await runs(ctx, long)
    [daily_run] = await runs(ctx, daily)
    # 14:20: the daily run times out at its 20 minutes; Run now of the long one queues.
    await ctx.habits.run_now(pixie.id, long.id)
    provider.script(hang())
    clock.advance(timedelta(minutes=20))
    await ctx.habit_scheduler.tick()

    assert running == "running"
    assert (timed_out.outcome, timed_out.reason) == ("timed_out", "ran past 120 minutes")
    assert (await session_of(ctx, timed_out)).state is SessionState.CLOSED
    assert (daily_run.outcome, daily_run.due_at) == (
        "running",
        clock.now() - timedelta(minutes=110),
    )
    assert [(r.outcome, r.reason) for r in await runs(ctx, daily)] == [
        ("timed_out", "ran past 20 minutes")
    ]
    assert ctx.habit_scheduler.current_run == (await runs(ctx, long))[0].id


async def test_a_scheduled_run_more_than_two_hours_late_is_skipped(
    ctx: AppContext, clock: FakeClock
) -> None:
    pixie = await make_pixie(ctx)
    daily = await make_habit(ctx, pixie.id, schedule={"kind": "daily", "time": "12:01"})

    # No check ran meanwhile, as while the Mac slept.
    clock.advance(timedelta(hours=2, minutes=2))
    await ctx.habit_scheduler.tick()

    [skipped] = await runs(ctx, daily)
    assert (skipped.outcome, skipped.reason) == ("skipped", LATE_REASON)
    assert skipped.due_at == clock.now() - timedelta(hours=2, minutes=1)
    assert (skipped.started_at, skipped.session_id) == (None, None)
    assert skipped.ended_at == clock.now()
    assert ctx.habit_scheduler.current_run is None


async def test_a_scheduled_time_is_queued_once_while_runs_wait(
    ctx: AppContext, provider: FakeProvider, clock: FakeClock
) -> None:
    pixie = await make_pixie(ctx)
    long = await make_habit(ctx, pixie.id, name="Long", max_minutes=120)
    hourly = await make_habit(ctx, pixie.id, schedule={"kind": "hourly", "minute": 30})
    provider.script(hang(), reply("ok"))
    await ctx.habits.run_now(pixie.id, long.id)
    await started(ctx, provider)
    clock.advance(timedelta(minutes=30))
    await ctx.habit_scheduler.tick()
    clock.advance(timedelta(minutes=60))
    await ctx.habit_scheduler.tick()
    queued = await runs(ctx, hourly)
    next_due = (await ctx.habits.list_habits(pixie.id))[1].next_due_at

    clock.advance(timedelta(minutes=30))
    await ctx.habit_scheduler.tick()
    await ended(ctx)

    # 12:30 and 13:30 came while the long run ran: one run for both.
    assert [r.outcome for r in queued] == ["queued"]
    assert queued[0].due_at == clock.now() - timedelta(minutes=90)
    assert next_due == clock.now() + timedelta(minutes=30)
    # The long run timed out at 14:00; the queued run then ran, 90 minutes late.
    assert [r.outcome for r in await runs(ctx, hourly)] == ["quiet"]


@pytest.mark.parametrize(
    ("window", "skipped"),
    [
        (UsageInfo(five_hour=UsageWindow(utilization=0.8, resets_at=None), seven_day=None), True),
        (UsageInfo(five_hour=None, seven_day=UsageWindow(utilization=0.95, resets_at=None)), True),
        (UsageInfo(five_hour=UsageWindow(utilization=0.79, resets_at=None), seven_day=None), False),
    ],
)
async def test_high_usage_skips_scheduled_runs(
    ctx: AppContext,
    provider: FakeProvider,
    clock: FakeClock,
    window: UsageInfo,
    skipped: bool,
) -> None:
    pixie = await make_pixie(ctx)
    habit = await make_habit(ctx, pixie.id, schedule={"kind": "daily", "time": "12:30"})
    await ctx.usage.update_limits(window)
    provider.script(reply("ok"))
    clock.advance(timedelta(minutes=30))

    await ctx.habit_scheduler.tick()
    await ended(ctx)

    [run] = await runs(ctx, habit)
    expected = ("skipped", USAGE_REASON) if skipped else ("quiet", None)
    assert (run.outcome, run.reason) == expected


async def test_a_usage_window_that_reset_does_not_count(
    ctx: AppContext, provider: FakeProvider, clock: FakeClock
) -> None:
    pixie = await make_pixie(ctx)
    habit = await make_habit(ctx, pixie.id, schedule={"kind": "daily", "time": "12:30"})
    reset = clock.now() + timedelta(minutes=10)
    await ctx.usage.update_limits(
        UsageInfo(five_hour=UsageWindow(utilization=0.9, resets_at=reset), seven_day=None)
    )
    provider.script(reply("ok"))
    clock.advance(timedelta(minutes=30))

    await ctx.habit_scheduler.tick()
    await ended(ctx)

    assert [r.outcome for r in await runs(ctx, habit)] == ["quiet"]


async def test_run_now_ignores_the_usage_and_a_pause(
    ctx: AppContext, provider: FakeProvider
) -> None:
    pixie = await make_pixie(ctx)
    habit = await make_habit(ctx, pixie.id, enabled=False)
    await ctx.usage.update_limits(
        UsageInfo(five_hour=UsageWindow(utilization=1.0, resets_at=None), seven_day=None)
    )
    provider.script(reply("ok"))

    run = await run_now(ctx, habit)

    assert run.outcome == "quiet"


async def test_pausing_skips_the_queued_scheduled_runs_but_not_run_now(
    ctx: AppContext, provider: FakeProvider, clock: FakeClock
) -> None:
    pixie = await make_pixie(ctx)
    long = await make_habit(ctx, pixie.id, name="Long")
    habit = await make_habit(ctx, pixie.id, schedule={"kind": "hourly", "minute": 5})
    provider.script(hang(), reply("ok"))
    await ctx.habits.run_now(pixie.id, long.id)
    await started(ctx, provider)
    clock.advance(timedelta(minutes=5))
    await ctx.habit_scheduler.tick()
    manual = await ctx.habits.run_now(pixie.id, habit.id)

    paused = await ctx.habits.update(pixie.id, habit.id, UpdateHabit(enabled=False))
    clock.advance(timedelta(minutes=20))
    await ctx.habit_scheduler.tick()
    await ended(ctx)

    assert paused.next_due_at is None
    assert [(r.id == manual.id, r.outcome, r.reason) for r in await runs(ctx, habit)] == [
        (True, "quiet", None),
        (False, "skipped", PAUSED_REASON),
    ]


async def test_a_queued_run_of_a_habit_paused_meanwhile_does_not_run(
    ctx: AppContext, clock: FakeClock
) -> None:
    pixie = await make_pixie(ctx)
    habit = await make_habit(ctx, pixie.id, enabled=False)
    stored = await ctx.habit_scheduler._store.get(habit.id)  # pyright: ignore[reportPrivateUsage]
    await ctx.habit_scheduler._store.add_run(stored, "schedule", clock.now())  # pyright: ignore[reportPrivateUsage]

    await ctx.habit_scheduler.tick()

    assert [(r.outcome, r.reason) for r in await runs(ctx, habit)] == [("skipped", PAUSED_REASON)]


async def test_a_run_waiting_on_an_approval_for_15_minutes_stalls(
    ctx: AppContext, provider: FakeProvider, clock: FakeClock
) -> None:
    pixie = await make_pixie(ctx)
    habit = await make_habit(ctx, pixie.id)
    provider.script(ask("Bash", reply("never")))
    await ctx.habits.run_now(pixie.id, habit.id)
    await ctx.habit_scheduler.tick()

    async def pending() -> bool:
        return bool(await ctx.approvals.list_approvals(ApprovalStatus.PENDING))

    await until(pending)
    [approval] = await ctx.approvals.list_approvals(ApprovalStatus.PENDING)
    clock.advance(timedelta(minutes=14))
    await ctx.habit_scheduler.tick()
    before = (await runs(ctx, habit))[0].outcome

    clock.advance(timedelta(minutes=1))
    await ctx.habit_scheduler.tick()

    [run] = await runs(ctx, habit)
    assert approval.repo == f"pixie:{pixie.id}"
    assert before == "running"
    assert (run.outcome, run.reason) == ("stalled", STALLED_REASON)
    assert (await ctx.approvals.get(approval.id)).status is ApprovalStatus.EXPIRED
    assert (await session_of(ctx, run)).state is SessionState.CLOSED


async def test_a_failed_run_records_its_error(ctx: AppContext, provider: FakeProvider) -> None:
    pixie = await make_pixie(ctx)
    habit = await make_habit(ctx, pixie.id)
    provider.script(engine_error("rate limited"))

    run = await run_now(ctx, habit)

    assert (run.outcome, run.reason) == ("failed", "rate limited")
    assert await published(ctx, types.NOTIFY) == []


async def test_an_interrupted_run_failed(ctx: AppContext, provider: FakeProvider) -> None:
    pixie = await make_pixie(ctx)
    habit = await make_habit(ctx, pixie.id)
    provider.script(until_interrupted())
    await ctx.habits.run_now(pixie.id, habit.id)
    await ctx.habit_scheduler.tick()
    [running] = await runs(ctx, habit)
    assert running.session_id is not None
    await until(lambda: bool(provider.runs and provider.runs[0].inputs))

    await ctx.sessions.interrupt(running.session_id)
    await ended(ctx)

    [run] = await runs(ctx, habit)
    assert (run.outcome, run.reason) == ("failed", INTERRUPTED_REASON)


async def test_a_run_that_cannot_start_failed(ctx: AppContext, clock: FakeClock) -> None:
    pixie = await make_pixie(ctx)
    habit = await make_habit(ctx, pixie.id)
    ctx.paths.pixies_dir.joinpath(pixie.id).rename(ctx.paths.pixies_dir / "moved")

    await ctx.habits.run_now(pixie.id, habit.id)
    await ctx.habit_scheduler.tick()

    [run] = await runs(ctx, habit)
    assert (run.outcome, run.reason) == ("failed", f"unknown pixie {pixie.id!r}")
    assert (run.started_at, run.ended_at, run.session_id) == (clock.now(), clock.now(), None)


async def test_the_latest_twenty_runs_are_kept_with_their_transcripts(
    ctx: AppContext, provider: FakeProvider
) -> None:
    pixie = await make_pixie(ctx)
    habit = await make_habit(ctx, pixie.id)
    first = None
    for n in range(KEEP_RUNS + 1):
        provider.script(reply(f"run {n}"))
        run = await run_now(ctx, habit)
        first = first or run

    kept = await runs(ctx, habit)

    assert first is not None
    assert first.session_id is not None
    assert len(kept) == KEEP_RUNS
    assert first.id not in {r.id for r in kept}
    assert not await ctx.db.fetch_all("SELECT id FROM sessions WHERE id = ?", (first.session_id,))
    states = {(await session_of(ctx, r)).state for r in kept}
    assert states == {SessionState.CLOSED}


async def test_runs_a_stopped_daemon_left_running_failed_and_queued_ones_stay(
    ctx: AppContext, provider: FakeProvider
) -> None:
    pixie = await make_pixie(ctx)
    habit = await make_habit(ctx, pixie.id)
    other = await make_habit(ctx, pixie.id, name="Other")
    provider.script(hang())
    scheduler = ctx.habit_scheduler
    await scheduler.start()
    await ctx.habits.run_now(pixie.id, habit.id)
    await until(lambda: scheduler.current_run is not None)
    await scheduler.stop()
    await ctx.habits.run_now(pixie.id, other.id)
    # The daemon stops its agents after the scheduler: the run is cut off.
    await ctx.sessions.shutdown()
    left = (await runs(ctx, habit))[0].outcome

    restarted = HabitScheduler(
        store=scheduler._store,  # pyright: ignore[reportPrivateUsage]
        events=scheduler._events,  # pyright: ignore[reportPrivateUsage]
        pixies=scheduler._pixies,  # pyright: ignore[reportPrivateUsage]
        files=scheduler._files,  # pyright: ignore[reportPrivateUsage]
        sessions=ctx.sessions,
        approvals=ctx.approvals,
        usage=ctx.usage,
        clock=ctx.clock,
        zone=None,
        defaults=lambda: ctx.settings.agents,
    )
    await restarted.recover()

    [run] = await runs(ctx, habit)
    assert left == "running"
    assert (run.outcome, run.reason) == ("failed", RESTARTED_REASON)
    assert [r.outcome for r in await runs(ctx, other)] == ["queued"]


async def test_deleting_the_habit_stops_its_run(ctx: AppContext, provider: FakeProvider) -> None:
    pixie = await make_pixie(ctx)
    habit = await make_habit(ctx, pixie.id)
    provider.script(hang())
    await ctx.habits.run_now(pixie.id, habit.id)
    await started(ctx, provider)
    [run] = await runs(ctx, habit)

    await ctx.habits.delete(pixie.id, habit.id)

    assert ctx.habit_scheduler.current_run is None
    assert provider.runs[0].closed
    assert not await ctx.db.fetch_all("SELECT id FROM sessions WHERE id = ?", (run.session_id,))
    assert not await ctx.db.fetch_all("SELECT id FROM pixie_habit_runs")


async def test_deleting_the_pixie_ends_its_run(ctx: AppContext, provider: FakeProvider) -> None:
    pixie = await make_pixie(ctx)
    habit = await make_habit(ctx, pixie.id)
    provider.script(hang())
    await ctx.habits.run_now(pixie.id, habit.id)
    await started(ctx, provider)

    await ctx.pixies.delete(pixie.id)
    await ended(ctx)

    assert not await ctx.db.fetch_all("SELECT id FROM pixie_habits WHERE id = ?", (habit.id,))
    assert not await ctx.db.fetch_all("SELECT id FROM sessions")


async def test_the_loop_checks_at_once_and_after_run_now(
    ctx: AppContext,
    provider: FakeProvider,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pixie = await make_pixie(ctx)
    habit = await make_habit(ctx, pixie.id)
    store = ctx.habit_scheduler._store  # pyright: ignore[reportPrivateUsage]
    queued = store.queued
    calls = 0

    async def failing_once() -> list[StoredRun]:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("database is locked")
        return await queued()

    monkeypatch.setattr(store, "queued", failing_once)
    provider.script(reply("ok"))
    with caplog.at_level(logging.WARNING):
        await ctx.habit_scheduler.start()
        await until(lambda: calls == 1)
        await ctx.habits.run_now(pixie.id, habit.id)
        await until(lambda: bool(provider.runs))
        await ended(ctx)

    assert "habit check failed (RuntimeError)" in caplog.text
    assert [r.outcome for r in await runs(ctx, habit)] == ["quiet"]


async def test_a_failed_end_is_logged_and_left_to_the_next_check(
    ctx: AppContext,
    provider: FakeProvider,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pixie = await make_pixie(ctx)
    habit = await make_habit(ctx, pixie.id)
    get = ctx.sessions.get
    failed = asyncio.Event()

    async def failing(session_id: str) -> Session:
        if not failed.is_set():
            failed.set()
            raise RuntimeError("database is locked")
        return await get(session_id)

    provider.script(reply("ok"))
    await ctx.habits.run_now(pixie.id, habit.id)
    await ctx.habit_scheduler.tick()
    monkeypatch.setattr(ctx.sessions, "get", failing)
    with caplog.at_level(logging.WARNING):
        await until(lambda: "ending a habit run failed (RuntimeError)" in caplog.text)
    still = ctx.habit_scheduler.current_run
    await ctx.habit_scheduler.tick()

    assert still is not None
    assert [r.outcome for r in await runs(ctx, habit)] == ["quiet"]


async def test_a_run_gone_with_its_pixie_ends_without_an_announcement(
    ctx: AppContext, provider: FakeProvider, clock: FakeClock
) -> None:
    pixie = await make_pixie(ctx)
    habit = await make_habit(ctx, pixie.id)
    provider.script(hang())
    await ctx.habits.run_now(pixie.id, habit.id)
    await started(ctx, provider)
    # As when its pixie is deleted while the run ends.
    await ctx.db.execute("DELETE FROM pixie_habit_runs")
    before = len(await published(ctx, types.HABIT_RUN_UPDATED))

    clock.advance(timedelta(minutes=20))
    await ctx.habit_scheduler.tick()

    assert ctx.habit_scheduler.current_run is None
    assert len(await published(ctx, types.HABIT_RUN_UPDATED)) == before
    assert provider.runs[0].closed
