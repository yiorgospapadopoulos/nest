"""Creating, changing, pausing, deleting and running a pixie's habits (B42)."""

from datetime import timedelta

import pytest
from pydantic import ValidationError

from harness.context import AppContext
from harness.errors import InvalidInputError
from harness.events import types
from harness.pixies.errors import PixieNotFoundError
from harness.pixies.habit_models import (
    NEEDS_A_START,
    CreateHabit,
    HabitIdea,
    UpdateHabit,
    problems,
    severity_at_least,
)
from harness.pixies.habit_store import HabitNotFoundError
from harness.sessions.models import SessionState
from tests.fake_provider import FakeProvider, reply
from tests.fakes import FakeClock
from tests.habit_support import (
    ctx,
    ended,
    make_habit,
    make_pixie,
    provider,
    published,
    run_now,
    runs,
)

__all__ = ["ctx", "provider"]


async def test_create_and_list(ctx: AppContext, clock: FakeClock) -> None:
    pixie = await make_pixie(ctx)
    other = await make_pixie(ctx, "Other")
    first = await make_habit(
        ctx,
        pixie.id,
        name="  Morning check ",
        schedule={"kind": "weekdays", "time": "12:30"},
        triggers=["failed", "ci_failed", "failed"],
        max_minutes=5,
    )
    clock.advance(timedelta(seconds=1))
    second = await make_habit(ctx, pixie.id, name="Watch", schedule=None, triggers=["stuck"])
    await make_habit(ctx, other.id)

    listed = await ctx.habits.list_habits(pixie.id)
    events = await published(ctx, types.HABIT_UPDATED)

    assert first.name == "Morning check"
    assert first.triggers == ["failed", "ci_failed"]
    assert (first.max_minutes, first.enabled) == (5, True)
    assert first.next_due_at == clock.now() + timedelta(minutes=30) - timedelta(seconds=1)
    assert (second.next_due_at, second.last_run) == (None, None)
    assert [h.id for h in listed] == [first.id, second.id]
    assert events[0]["habit"] == first.model_dump(mode="json")
    assert await ctx.habits.get(pixie.id, second.id) == second


async def test_a_habit_needs_a_schedule_or_a_trigger() -> None:
    with pytest.raises(ValidationError) as error:
        CreateHabit.model_validate({"name": "N", "prompt": "P"})
    with pytest.raises(ValidationError) as bad_time:
        HabitIdea.model_validate(
            {"name": "N", "prompt": "P", "schedule": {"kind": "daily", "time": "25:00"}}
        )

    assert problems(error.value) == f"{NEEDS_A_START}."
    assert problems(bad_time.value).startswith("schedule.daily.time: String should match")


def test_severities_in_order() -> None:
    assert severity_at_least("action", "warn")
    assert severity_at_least("warn", "warn")
    assert not severity_at_least("info", "warn")


async def test_unknown_pixies_and_habits(ctx: AppContext) -> None:
    pixie = await make_pixie(ctx)
    other = await make_pixie(ctx, "Other")
    habit = await make_habit(ctx, pixie.id)

    with pytest.raises(PixieNotFoundError):
        await ctx.habits.list_habits("nope")
    with pytest.raises(PixieNotFoundError):
        await make_habit(ctx, "nope")
    with pytest.raises(HabitNotFoundError):
        await ctx.habits.get(pixie.id, "nope")
    # Another pixie's habit is not this one's.
    with pytest.raises(HabitNotFoundError):
        await ctx.habits.update(other.id, habit.id, UpdateHabit(name="Mine"))
    with pytest.raises(HabitNotFoundError):
        await ctx.habits.run_now(other.id, habit.id)


async def test_update_changes_only_what_is_given(ctx: AppContext) -> None:
    pixie = await make_pixie(ctx)
    habit = await make_habit(ctx, pixie.id, triggers=["stuck"])

    renamed = await ctx.habits.update(pixie.id, habit.id, UpdateHabit(name="Renamed"))
    retriggered = await ctx.habits.update(
        pixie.id, habit.id, UpdateHabit(triggers=["failed", "failed", "stuck"])
    )
    unscheduled = await ctx.habits.update(
        pixie.id, habit.id, UpdateHabit.model_validate({"schedule": None})
    )

    assert (renamed.name, renamed.prompt, renamed.schedule) == (
        "Renamed",
        habit.prompt,
        habit.schedule,
    )
    assert retriggered.triggers == ["failed", "stuck"]
    assert (unscheduled.schedule, unscheduled.next_due_at) == (None, None)
    with pytest.raises(InvalidInputError, match=NEEDS_A_START):
        await ctx.habits.update(pixie.id, habit.id, UpdateHabit(triggers=[]))
    assert (await ctx.habits.get(pixie.id, habit.id)).triggers == ["failed", "stuck"]


async def test_a_new_schedule_and_resuming_count_from_now(
    ctx: AppContext, clock: FakeClock
) -> None:
    pixie = await make_pixie(ctx)
    habit = await make_habit(ctx, pixie.id, schedule={"kind": "daily", "time": "12:10"})
    paused = await ctx.habits.update(pixie.id, habit.id, UpdateHabit(enabled=False))
    clock.advance(timedelta(minutes=20))

    resumed = await ctx.habits.update(pixie.id, habit.id, UpdateHabit(enabled=True))
    await ctx.habit_scheduler.tick()
    clock.advance(timedelta(minutes=5))
    moved = await ctx.habits.update(
        pixie.id,
        habit.id,
        UpdateHabit.model_validate({"schedule": {"kind": "daily", "time": "12:00"}}),
    )
    same = await ctx.habits.update(
        pixie.id,
        habit.id,
        UpdateHabit.model_validate({"schedule": {"kind": "daily", "time": "12:00"}}),
    )
    await ctx.habit_scheduler.tick()

    # 12:10 passed while paused, and 12:00 before the new schedule: neither runs.
    assert await runs(ctx, habit) == []
    assert paused.next_due_at is None
    assert resumed.next_due_at == clock.now() + timedelta(days=1) - timedelta(minutes=15)
    assert moved.next_due_at == clock.now() + timedelta(days=1) - timedelta(minutes=25)
    assert same == moved


async def test_run_now_queues_and_the_history_lists_runs(
    ctx: AppContext, provider: FakeProvider, clock: FakeClock
) -> None:
    pixie = await make_pixie(ctx)
    habit = await make_habit(ctx, pixie.id)

    queued = await ctx.habits.run_now(pixie.id, habit.id)
    listed = await runs(ctx, habit)
    provider.script(reply("ok"))
    await ctx.habit_scheduler.tick()
    await ended(ctx)

    assert (queued.outcome, queued.due_at, queued.session_id) == ("queued", clock.now(), None)
    assert listed == [queued]
    assert [r.outcome for r in await runs(ctx, habit)] == ["quiet"]


async def test_deleting_a_habit_deletes_its_runs_and_their_transcripts(
    ctx: AppContext, provider: FakeProvider
) -> None:
    pixie = await make_pixie(ctx)
    habit = await make_habit(ctx, pixie.id)
    kept = await make_habit(ctx, pixie.id, name="Kept")
    provider.script(reply("ok"))
    run = await run_now(ctx, habit)
    await ctx.habits.run_now(pixie.id, habit.id)

    await ctx.habits.delete(pixie.id, habit.id)

    assert run.session_id is not None
    assert not await ctx.db.fetch_all("SELECT id FROM sessions WHERE id = ?", (run.session_id,))
    assert not await ctx.db.fetch_all("SELECT id FROM pixie_habit_runs")
    assert [h.id for h in await ctx.habits.list_habits(pixie.id)] == [kept.id]
    assert (await published(ctx, types.HABIT_DELETED)) == [{"id": habit.id, "pixie_id": pixie.id}]
    with pytest.raises(HabitNotFoundError):
        await ctx.habits.delete(pixie.id, habit.id)


async def test_a_pixie_takes_its_habits_and_their_runs_along(
    ctx: AppContext, provider: FakeProvider
) -> None:
    pixie = await make_pixie(ctx)
    habit = await make_habit(ctx, pixie.id)
    provider.script(reply("ok"))
    run = await run_now(ctx, habit)
    session = await ctx.sessions.get(run.session_id or "")

    await ctx.pixies.delete(pixie.id)

    assert session.state is SessionState.CLOSED
    for table in ("pixie_habits", "pixie_habit_runs", "sessions"):
        assert not await ctx.db.fetch_all(f"SELECT * FROM {table}")  # noqa: S608
