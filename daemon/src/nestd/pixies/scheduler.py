"""Runs pixies' habits (B42): one run at a time across all pixies, from a queue in due order.

A loop checks every 15 seconds, like the pull request tracker (D034). Each check ends the
current run when it went past its habit's minutes or an approval of it waited too long,
queues the newest scheduled time of each enabled habit that came due, and starts the next
run that is due. A scheduled run more than 2 hours late, and a scheduled or triggered run
while the Claude usage is high (`[pixies] habit_usage_percent`) or all habits are paused
(`[pixies] habits_paused`, D104), is recorded as skipped instead; Run now always runs.

A run is a fresh session of the pixie, never resumed, marked with the run; it ends with its
first turn. Runs left running by a daemon that stopped count as failed.
"""

import asyncio
import logging
from collections.abc import Callable, Coroutine
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timedelta, tzinfo

from pydantic import JsonValue

from nestd.approvals.models import ApprovalStatus
from nestd.approvals.queue import ApprovalQueue
from nestd.clock import Clock
from nestd.config.models import AgentDefaults, PixieDefaults
from nestd.errors import NestError
from nestd.pixies.files import PixieFiles
from nestd.pixies.habit_events import HabitEvents
from nestd.pixies.habit_models import RunOutcome
from nestd.pixies.habit_store import HabitStore, StoredHabit, StoredRun
from nestd.pixies.prompt import habit_message
from nestd.pixies.schedule import latest_due
from nestd.pixies.store import PixieStore
from nestd.sessions.errors import SessionNotFoundError
from nestd.sessions.manager import SessionManager
from nestd.sessions.models import Session, SessionState
from nestd.usage.store import UsageStore

logger = logging.getLogger(__name__)

TICK = timedelta(seconds=15)
# A scheduled run that would start later than this after its time is skipped.
LATE = timedelta(hours=2)
# A run whose approval waits this long is stopped.
STALL = timedelta(minutes=15)
# A triggered habit runs at most once in this long.
TRIGGER_SPACING = timedelta(minutes=5)
# Events one triggered run lists at most; the newest are kept.
MAX_EVENTS = 50

LATE_REASON = "late"
USAGE_REASON = "usage"
PAUSED_REASON = "paused"
HABITS_PAUSED_REASON = "all habits paused"
RESTARTED_REASON = "daemon restarted"
INTERRUPTED_REASON = "interrupted"
GONE_REASON = "its session was deleted"
STALLED_REASON = "an approval waited 15 minutes"

FINISHED = frozenset(
    {SessionState.IDLE, SessionState.FAILED, SessionState.INTERRUPTED, SessionState.CLOSED}
)


@dataclass(frozen=True)
class _Current:
    run_id: str
    habit_id: str
    session_id: str
    started_at: datetime
    max_minutes: int


class HabitScheduler:
    def __init__(
        self,
        *,
        store: HabitStore,
        events: HabitEvents,
        pixies: PixieStore,
        files: PixieFiles,
        sessions: SessionManager,
        approvals: ApprovalQueue,
        usage: UsageStore,
        clock: Clock,
        zone: tzinfo | None,
        defaults: Callable[[], AgentDefaults],
        pixie_settings: Callable[[], PixieDefaults],
        tick: timedelta = TICK,
    ) -> None:
        """`zone` is the one schedules are read in; None is the system's zone. `defaults`
        gives the model of a pixie without its own; `pixie_settings` whether habits are
        paused and at which usage runs are skipped (D104), read at each check.
        """
        self._store = store
        self._events = events
        self._pixies = pixies
        self._files = files
        self._sessions = sessions
        self._approvals = approvals
        self._usage = usage
        self._clock = clock
        self._zone = zone
        self._defaults = defaults
        self._pixie_settings = pixie_settings
        self._tick = tick
        # Checks, starts and ends one at a time.
        self._lock = asyncio.Lock()
        self._current: _Current | None = None
        self._wake = asyncio.Event()
        self._loop_task: asyncio.Task[None] | None = None
        self._tasks: set[asyncio.Task[None]] = set()
        # Set while the daemon stops: the runs it interrupts then count as restarted.
        self._stopped = False

    @property
    def current_run(self) -> str | None:
        """The id of the run in progress, if any."""
        return None if self._current is None else self._current.run_id

    async def start(self) -> None:
        self._stopped = False
        await self.recover()
        self._loop_task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        """Stop after the check in progress, so a run never starts halfway."""
        self._stopped = True
        async with self._lock:
            tasks = [*self._tasks, *([self._loop_task] if self._loop_task else [])]
            self._tasks, self._loop_task = set(), None
            for task in tasks:
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def wake(self) -> None:
        """Check at once, as after Run now or new events."""
        self._wake.set()

    async def recover(self) -> None:
        """Runs a stopped daemon left running have failed; queued ones stay queued."""
        for run_id, session_id in await self._store.running():
            await self._record(run_id, "failed", RESTARTED_REASON)
            await self._close(session_id)

    async def tick(self) -> None:
        async with self._lock:
            now = self._clock.now()
            await self._check_current(now)
            await self._queue_scheduled(now)
            while self._current is None and await self._start_next(now):
                continue

    async def queue_trigger(self, habit: StoredHabit, event: dict[str, JsonValue]) -> None:
        """Add an event to the habit's queued triggered run, or queue one: at once, or 5
        minutes after its last triggered run.
        """
        async with self._lock:
            queued = await self._store.queued_of(habit.id, "trigger")
            if queued is not None:
                events = [*(queued.trigger_events or []), event][-MAX_EVENTS:]
                await self._store.set_trigger_events(queued.id, events)
                return
            now = self._clock.now()
            last = await self._store.last_triggered_at(habit.id)
            due = now if last is None else max(now, last + TRIGGER_SPACING)
            await self._events.run(await self._store.add_run(habit, "trigger", due, [event]))
        self.wake()

    async def paused(self, habit_id: str) -> None:
        """A paused habit's scheduled and triggered runs leave the queue as skipped."""
        async with self._lock:
            for run in await self._store.queued():
                if run.habit_id == habit_id and run.kind != "manual":
                    await self._record(run.id, "skipped", PAUSED_REASON)

    async def delete_habit(self, habit_id: str) -> list[str]:
        """Stop the habit's run in progress, if any, and delete the habit with its runs;
        returns the sessions of its runs. Between two checks, so none of its runs starts.
        """
        async with self._lock:
            current = self._current
            if current is not None and current.habit_id == habit_id:
                self._current = None
                await self._close(current.session_id)
            sessions = await self._store.sessions_of(habit_id)
            await self._store.delete(habit_id)
        self.wake()
        return sessions

    # Session hooks: a run ends with its session's first turn.

    async def state_changed(self, session: Session) -> None:
        if not self._stopped and session.habit_run_id is not None and session.state in FINISHED:
            self._spawn(self._settle(session.id))

    async def purged(self, session_id: str) -> None:
        current = self._current
        if not self._stopped and current is not None and current.session_id == session_id:
            self._spawn(self._settle(session_id))

    def _spawn(self, work: Coroutine[None, None, None]) -> None:
        task = asyncio.create_task(work)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _settle(self, session_id: str) -> None:
        """End the current run if its session has finished; checked under the lock, so a
        run that finishes while it starts is ended once it has.
        """
        try:
            async with self._lock:
                current = self._current
                if current is not None and current.session_id == session_id:
                    await self._end_if_finished(current)
        except Exception as error:
            # The next check ends it.
            logger.warning("ending a habit run failed (%s)", type(error).__name__)

    # Checks

    async def _check_current(self, now: datetime) -> None:
        current = self._current
        if current is None or await self._end_if_finished(current):
            return
        if now - current.started_at >= timedelta(minutes=current.max_minutes):
            await self._end(current, "timed_out", f"ran past {current.max_minutes} minutes")
            return
        waiting = [
            approval.created_at
            for approval in await self._approvals.list_approvals(ApprovalStatus.PENDING)
            if approval.session_id == current.session_id
        ]
        if waiting and now - min(waiting) >= STALL:
            await self._end(current, "stalled", STALLED_REASON)

    async def _end_if_finished(self, current: _Current) -> bool:
        try:
            session = await self._sessions.get(current.session_id)
        except SessionNotFoundError:
            await self._end(current, "failed", GONE_REASON)
            return True
        if session.state not in FINISHED:
            return False
        if session.state is SessionState.IDLE:
            await self._end(current, None, None)
        elif session.state is SessionState.FAILED:
            await self._end(current, "failed", session.last_error or "the run failed")
        else:
            await self._end(current, "failed", INTERRUPTED_REASON)
        return True

    async def _queue_scheduled(self, now: datetime) -> None:
        for habit in await self._store.enabled():
            if habit.schedule is None:
                continue
            due = latest_due(habit.schedule, habit.scheduled_through, now, self._zone)
            if due is None:
                continue
            await self._store.mark_scheduled(habit.id, due)
            if await self._store.queued_of(habit.id, "schedule") is None:
                await self._events.run(await self._store.add_run(habit, "schedule", due))
            else:
                # It runs once for both times; its next time moved on.
                await self._events.habit(habit.id)

    async def _start_next(self, now: datetime) -> bool:
        """Start the earliest due run, or record why it does not run; False when none is
        due.
        """
        due = [
            (run, run.due_at)
            for run in await self._store.queued()
            if run.due_at is not None and run.due_at <= now
        ]
        if not due:
            return False
        run, due_at = due[0]
        # A habit's runs go with it, so a queued run's habit is there.
        habit = await self._store.get(run.habit_id)
        skip = await self._skip_reason(run, due_at, habit, now)
        if skip is not None:
            await self._record(run.id, "skipped", skip)
            return True
        await self._start(run, habit, now)
        return True

    async def _skip_reason(
        self, run: StoredRun, due_at: datetime, habit: StoredHabit, now: datetime
    ) -> str | None:
        if run.kind == "manual":
            return None
        if not habit.enabled:
            return PAUSED_REASON
        if self._pixie_settings().habits_paused:
            return HABITS_PAUSED_REASON
        if run.kind == "schedule" and now - due_at > LATE:
            return LATE_REASON
        if await self._usage_high(now):
            return USAGE_REASON
        return None

    async def _usage_high(self, now: datetime) -> bool:
        """Whether the latest known 5-hour or weekly usage is at the limit; a window that
        has reset since does not count.
        """
        limits = await self._usage.limits()
        level = self._pixie_settings().habit_usage_percent / 100
        return any(
            window is not None
            and window.utilization >= level
            and (window.resets_at is None or window.resets_at > now)
            for window in (limits.five_hour, limits.seven_day)
        )

    async def _start(self, run: StoredRun, habit: StoredHabit, now: datetime) -> None:
        try:
            pixie = await self._pixies.get(habit.pixie_id)
            session = await self._sessions.create_pixie_chat(
                pixie_id=pixie.id,
                cwd=self._files.workdir(pixie.id),
                prompt=habit_message(habit.name, habit.prompt, run.trigger_events),
                title=habit.name,
                model=pixie.model or self._defaults().model,
                effort=pixie.effort,
                permission_mode=pixie.permission_mode,
                attachment_ids=[],
                habit_run_id=run.id,
            )
        except NestError as error:
            await self._record(run.id, "failed", str(error), started_at=now)
            return
        self._current = _Current(run.id, habit.id, session.id, now, habit.max_minutes)
        await self._update(run.id, outcome="running", session_id=session.id, started_at=now)

    async def _end(self, current: _Current, outcome: RunOutcome | None, reason: str | None) -> None:
        """Record how the run ended (None: reported or quiet, by whether it reported),
        close its session, and keep the habit's latest runs.
        """
        try:
            if outcome is None:
                run = await self._store.run(current.run_id)
                reported = run is not None and run.report_title is not None
                outcome = "reported" if reported else "quiet"
            await self._record(current.run_id, outcome, reason)
            await self._close(current.session_id)
            for session_id in await self._store.prune(current.habit_id):
                with suppress(NestError):
                    await self._sessions.purge(session_id)
        finally:
            # In progress until here: its session closing is no other run's end.
            self._current = None
            self.wake()

    async def _record(
        self,
        run_id: str,
        outcome: RunOutcome,
        reason: str | None,
        started_at: datetime | None = None,
    ) -> None:
        changes: dict[str, object] = {
            "outcome": outcome,
            "reason": reason,
            "ended_at": self._clock.now(),
        }
        if started_at is not None:
            changes["started_at"] = started_at
        await self._update(run_id, **changes)

    async def _update(self, run_id: str, **changes: object) -> None:
        """Change the run and announce it, unless it went with its pixie meanwhile."""
        run = await self._store.update_run(run_id, **changes)
        if run is not None:
            await self._events.run(run)

    async def _close(self, session_id: str) -> None:
        """Stop the run's agent; its transcript stays for the history. One that is closed
        or gone already is left as it is.
        """
        with suppress(NestError):
            await self._sessions.close(session_id, remove_worktree=False)

    async def _loop(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception as error:
                logger.warning("habit check failed (%s)", type(error).__name__)
            with suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), self._tick.total_seconds())
            self._wake.clear()
