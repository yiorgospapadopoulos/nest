"""Create, change, pause, delete and run a pixie's habits (B42)."""

from contextlib import suppress

from harness.clock import Clock
from harness.errors import HarnessError, InvalidInputError
from harness.pixies.habit_events import HabitEvents
from harness.pixies.habit_models import NEEDS_A_START, CreateHabit, Habit, HabitRun, UpdateHabit
from harness.pixies.habit_store import HabitNotFoundError, HabitStore, StoredHabit
from harness.pixies.scheduler import HabitScheduler
from harness.pixies.store import PixieStore
from harness.sessions.manager import SessionManager


class HabitService:
    def __init__(
        self,
        *,
        store: HabitStore,
        pixies: PixieStore,
        events: HabitEvents,
        scheduler: HabitScheduler,
        sessions: SessionManager,
        clock: Clock,
    ) -> None:
        self._store = store
        self._pixies = pixies
        self._events = events
        self._scheduler = scheduler
        self._sessions = sessions
        self._clock = clock

    async def list_habits(self, pixie_id: str) -> list[Habit]:
        """The pixie's habits, oldest first; 404 for an unknown pixie."""
        await self._pixies.get(pixie_id)
        return [await self._events.payload(h) for h in await self._store.of_pixie(pixie_id)]

    async def get(self, pixie_id: str, habit_id: str) -> Habit:
        return await self._events.payload(await self._own(pixie_id, habit_id))

    async def create(self, pixie_id: str, request: CreateHabit) -> Habit:
        await self._pixies.get(pixie_id)
        habit = await self._store.create(pixie_id, request)
        return await self._announce(habit.id)

    async def update(self, pixie_id: str, habit_id: str, request: UpdateHabit) -> Habit:
        """Fields left out are unchanged; an explicit null schedule removes it. 422 when the
        habit would have neither a schedule nor a trigger. A new schedule, and resuming,
        count from now: earlier times do not run.
        """
        before = await self._own(pixie_id, habit_id)
        changes = request.model_dump(exclude_none=True, exclude={"schedule"})
        if "schedule" in request.model_fields_set:
            changes["schedule"] = request.schedule
        schedule = changes.get("schedule", before.schedule)
        if schedule is None and not changes.get("triggers", before.triggers):
            raise InvalidInputError(NEEDS_A_START)
        if "triggers" in changes:
            changes["triggers"] = list(dict.fromkeys(changes["triggers"]))
        resumed = changes.get("enabled") is True and not before.enabled
        if resumed or ("schedule" in changes and schedule != before.schedule):
            changes["scheduled_through"] = self._clock.now()
        await self._store.update(habit_id, **changes)
        if changes.get("enabled") is False and before.enabled:
            await self._scheduler.paused(habit_id)
        return await self._announce(habit_id)

    async def delete(self, pixie_id: str, habit_id: str) -> None:
        """Stops its run in progress and deletes it with its runs and their transcripts."""
        habit = await self._own(pixie_id, habit_id)
        for session_id in await self._scheduler.delete_habit(habit_id):
            with suppress(HarnessError):
                await self._sessions.purge(session_id)
        await self._events.deleted(habit)

    async def run_now(self, pixie_id: str, habit_id: str) -> HabitRun:
        """Queue a run that starts as soon as no other runs, late or not, whatever the
        usage and even while the habit is paused.
        """
        habit = await self._own(pixie_id, habit_id)
        run = await self._store.add_run(habit, "manual", self._clock.now())
        await self._events.run(run)
        self._scheduler.wake()
        return run

    async def runs(self, pixie_id: str, habit_id: str) -> list[HabitRun]:
        """Newest first: the latest finished runs and any queued or running."""
        await self._own(pixie_id, habit_id)
        return list(await self._store.runs(habit_id))

    async def _own(self, pixie_id: str, habit_id: str) -> StoredHabit:
        await self._pixies.get(pixie_id)
        habit = await self._store.get(habit_id)
        if habit.pixie_id != pixie_id:
            msg = f"unknown habit {habit_id!r}"
            raise HabitNotFoundError(msg)
        return habit

    async def _announce(self, habit_id: str) -> Habit:
        return await self._events.announce(await self._store.get(habit_id))
