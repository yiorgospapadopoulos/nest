"""Habits as clients see them, and the events that keep clients' copies current (B42)."""

from contextlib import suppress
from datetime import tzinfo

from nestd.clock import Clock
from nestd.events import types
from nestd.events.bus import EventBus
from nestd.pixies.habit_models import Habit, HabitRun
from nestd.pixies.habit_store import HabitNotFoundError, HabitStore, StoredHabit
from nestd.pixies.schedule import next_due


class HabitEvents:
    def __init__(self, store: HabitStore, bus: EventBus, clock: Clock, zone: tzinfo | None) -> None:
        """`zone` is the one schedules are read in; None is the system's zone."""
        self._store = store
        self._bus = bus
        self._clock = clock
        self._zone = zone

    async def payload(self, habit: StoredHabit) -> Habit:
        due = None
        if habit.enabled and habit.schedule is not None:
            after = max(habit.scheduled_through, self._clock.now())
            due = next_due(habit.schedule, after, self._zone)
        last = await self._store.last_run(habit.id)
        return Habit.model_validate(
            {
                **habit.model_dump(exclude={"scheduled_through"}),
                "next_due_at": due,
                "last_run": None if last is None else HabitRun.model_validate(last.model_dump()),
            }
        )

    async def announce(self, stored: StoredHabit) -> Habit:
        habit = await self.payload(stored)
        await self._bus.publish(types.HABIT_UPDATED, {"habit": habit.model_dump(mode="json")})
        return habit

    async def habit(self, habit_id: str) -> None:
        """Announce the habit as it is now, unless it is gone."""
        with suppress(HabitNotFoundError):
            await self.announce(await self._store.get(habit_id))

    async def run(self, run: HabitRun) -> None:
        """Announce a run's new outcome, then its habit, whose last run or next time moved."""
        # A stored run leaves out its kind and events.
        await self._bus.publish(types.HABIT_RUN_UPDATED, {"run": run.model_dump(mode="json")})
        await self.habit(run.habit_id)

    async def deleted(self, habit: StoredHabit) -> None:
        await self._bus.publish(types.HABIT_DELETED, {"id": habit.id, "pixie_id": habit.pixie_id})
