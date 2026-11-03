"""Settings > Performance (B115): one run at a time in the background, its sections one
after another, and the page built from each section's latest and previous results."""

import asyncio
import logging
from collections.abc import Mapping, Sequence
from contextlib import suppress
from datetime import datetime

from nestd.clock import Clock
from nestd.errors import ConflictError, InvalidInputError
from nestd.events import types
from nestd.events.bus import EventBus
from nestd.perf.changes import Measurement, by_id, metric_view, what_changed
from nestd.perf.collectors import Collector
from nestd.perf.models import (
    Collected,
    LastRun,
    Measured,
    MetricView,
    PerfRun,
    PerfView,
    RunningView,
    SectionView,
)
from nestd.perf.sections import BY_ID, CARDS, DAEMON_SECTIONS, SECTIONS, MetricSpec, Section
from nestd.perf.store import Build, PerfStore

logger = logging.getLogger(__name__)


class Perf:
    def __init__(
        self,
        store: PerfStore,
        bus: EventBus,
        clock: Clock,
        collectors: Mapping[str, Collector],
        build: Build,
        machine: str,
        machine_noun: str = "Mac",
    ) -> None:
        """`collectors` has one per daemon section; a section without one reports that
        it cannot be measured here."""
        self._store = store
        self._bus = bus
        self._clock = clock
        self.collectors = dict(collectors)
        self._build = build
        self._machine = machine
        self._machine_noun = machine_noun
        self._task: asyncio.Task[None] | None = None
        self._starting = asyncio.Lock()

    async def started(self, ready_ms: int) -> None:
        """At startup: a run cut off by the restart failed, and this start is recorded."""
        await self._store.fail_running()
        await self._store.record_start(ready_ms, self._build)

    async def stop(self) -> None:
        """At shutdown: the run in progress stops; the next start marks it failed."""
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    async def settled(self) -> None:
        """Wait for the run in progress, if any (tests)."""
        if self._task is not None:
            with suppress(asyncio.CancelledError):
                await self._task

    async def start(self, sections: Sequence[str]) -> PerfView:
        """Run `sections` (empty: every daemon section) in the background; 409 while
        another run runs, 422 for an unknown section or the Mac app's."""
        chosen = list(dict.fromkeys(sections)) or list(DAEMON_SECTIONS)
        unknown = [s for s in chosen if s not in BY_ID or BY_ID[s].runner != "daemon"]
        if unknown:
            msg = f"cannot run {', '.join(unknown)} here; sections: {', '.join(DAEMON_SECTIONS)}"
            raise InvalidInputError(msg)
        async with self._starting:
            if await self._store.running() is not None:
                msg = "a performance run is already running"
                raise ConflictError(msg)
            ordered = [s for s in DAEMON_SECTIONS if s in chosen]
            run = await self._store.create(ordered, self._build, self._machine)
        await self._announce(run.id, "running")
        self._task = asyncio.create_task(self._run(run))
        return await self.view()

    async def record_client(self, section: str, values: Mapping[str, float | None]) -> PerfView:
        """A client measured its own section (the Mac app): a finished run of that one
        section. Metrics the section does not have are ignored."""
        spec = BY_ID.get(section)
        if spec is None or spec.runner == "daemon":
            clients = ", ".join(s.id for s in SECTIONS if s.runner != "daemon")
            msg = f"{section} is not measured by a client; client sections: {clients}"
            raise InvalidInputError(msg)
        result = Collected(
            metrics=[
                Measured(
                    id=m.id, label=m.label, unit=m.unit, better=m.better, value=values.get(m.id)
                )
                for m in spec.metrics
            ]
        )
        run = await self._store.create([section], self._build, self._machine)
        await self._store.finish(run.id, {section: result})
        await self._announce(run.id, "done")
        return await self.view()

    async def clear(self) -> PerfView:
        await self._store.clear_old()
        return await self.view()

    async def view(self) -> PerfView:
        running = await self._store.running()
        done = await self._store.done()
        measured = {section.id: _measurement(section.id, done) for section in SECTIONS}
        sections = [
            _section_view(s, measured[s.id], _error(s.id, done), self._machine_noun)
            for s in SECTIONS
        ]
        views = {s.id: {m.id: m for m in s.metrics} for s in sections}
        cards = [views[c.section].get(c.metric.id) or _unmeasured(c.metric) for c in CARDS]
        # The header's last run is the daemon's: a client's result takes no time here.
        latest = next((run for run in done if set(run.sections) & set(DAEMON_SECTIONS)), None)
        return PerfView(
            running=None
            if running is None
            else RunningView(
                id=running.id, sections=running.sections, started_at=running.started_at
            ),
            last_run=None if latest is None else _last_run(latest),
            cards=cards,
            sections=sections,
            changes=what_changed(
                [(BY_ID[sid].title, m) for sid, m in measured.items() if m is not None]
            ),
            runs=await self._store.count(),
        )

    async def _run(self, run: PerfRun) -> None:
        results: dict[str, Collected] = {}
        try:
            for section in run.sections:
                results[section] = await self._section(section)
            await self._store.finish(run.id, results)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            logger.exception("The performance run %s failed", run.id)
            await self._store.fail(run.id, type(error).__name__)
            await self._announce(run.id, "failed")
            return
        await self._announce(run.id, "done")

    async def _section(self, section: str) -> Collected:
        collector = self.collectors.get(section)
        if collector is None:
            return Collected(error="Not measured on this daemon.")
        try:
            return await collector()
        except asyncio.CancelledError:
            raise
        except Exception as error:
            logger.warning("Performance section %s failed", section, exc_info=True)
            return Collected(error=_reason(error))

    async def _announce(self, run_id: str, state: str) -> None:
        await self._bus.publish_ephemeral(types.PERF_RUN, {"id": run_id, "state": state})


def _measurement(section: str, done: list[PerfRun]) -> Measurement | None:
    """The section's newest measured result and the one before it."""
    found = [(run, run.results[section]) for run in done if _measured(run, section)]
    if not found:
        return None
    (latest_run, latest), rest = found[0], found[1:]
    previous_run, previous = rest[0] if rest else (None, None)
    return Measurement(latest, latest_run, previous, previous_run)


def _measured(run: PerfRun, section: str) -> bool:
    result = run.results.get(section)
    return result is not None and result.error is None


def _error(section: str, done: list[PerfRun]) -> tuple[str, datetime] | None:
    """The newest attempt's error, when it came after the newest measured result."""
    for run in done:
        result = run.results.get(section)
        if result is None:
            continue
        if result.error is None:
            return None
        return result.error, run.finished_at or run.started_at
    return None


def _section_view(
    section: Section,
    measurement: Measurement | None,
    error: tuple[str, datetime] | None,
    machine_noun: str,
) -> SectionView:
    metrics: list[MetricView] = []
    ran_at: datetime | None = None
    # A section's note may name the machine as {machine}.
    note = section.note.format(machine=machine_noun) if section.note else section.note
    series = None
    if measurement is not None:
        before = by_id(measurement.previous)
        metrics = [metric_view(m, before.get(m.id)) for m in measurement.latest.metrics]
        ran_at = measurement.latest_run.finished_at
        note = measurement.latest.note or note
        series = measurement.latest.series
    elif section.metrics:
        # A client's section before its first result: its metrics, not yet measured.
        metrics = [_unmeasured(m) for m in section.metrics]
    return SectionView(
        id=section.id,
        title=section.title,
        advanced=section.advanced,
        runner=section.runner,
        live=section.live,
        ran_at=error[1] if error is not None else ran_at,
        error=None if error is None else error[0],
        note=note,
        metrics=metrics,
        series=series,
    )


def _unmeasured(spec: MetricSpec) -> MetricView:
    return metric_view(
        Measured(id=spec.id, label=spec.label, unit=spec.unit, better=spec.better, value=None),
        None,
    )


def _last_run(run: PerfRun) -> LastRun | None:
    if run.finished_at is None:
        return None
    ms = round((run.finished_at - run.started_at).total_seconds() * 1000)
    return LastRun(finished_at=run.finished_at, duration_ms=ms)


def _reason(error: Exception) -> str:
    """Short, and never what an engine printed: that may quote the user's setup."""
    if isinstance(error, TimeoutError):
        return "Timed out."
    return f"Could not measure it ({type(error).__name__})."
