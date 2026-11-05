"""B115: performance runs, each section against the run before, and keeping old runs."""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import timedelta

import pytest

from nestd.errors import ConflictError, InvalidInputError
from nestd.events.bus import EventBus
from nestd.perf.collectors import Collector
from nestd.perf.models import Collected, Measured, PerfView, SectionView
from nestd.perf.service import Perf
from nestd.perf.store import RESTARTED, Build, PerfStore
from nestd.storage.db import Database
from tests.fakes import FakeClock

BUILD = Build(version="1.0.0", git_commit="abc")


def tokens(value: float, metric: str = "total") -> Collected:
    return Collected(
        metrics=[Measured(id=metric, label="Total", unit="tokens", better="lower", value=value)]
    )


class Script:
    """A collector that returns the next scripted result each run."""

    def __init__(self, *results: Collected | Exception) -> None:
        self.results = list(results)
        self.calls = 0

    async def __call__(self) -> Collected:
        self.calls += 1
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def make_perf(
    db: Database,
    clock: FakeClock,
    collectors: dict[str, Collector],
    build: Build = BUILD,
) -> Perf:
    return Perf(PerfStore(db, clock), EventBus(db, clock), clock, collectors, build, "Test Mac")


async def run(perf: Perf, clock: FakeClock, *sections: str) -> PerfView:
    await perf.start(list(sections))
    await perf.settled()
    clock.advance(timedelta(minutes=1))
    return await perf.view()


def section(view: PerfView, section_id: str) -> SectionView:
    return next(s for s in view.sections if s.id == section_id)


async def test_each_metric_is_compared_with_the_previous_run_of_its_section(
    db: Database, clock: FakeClock
) -> None:
    context = Script(tokens(20_000), tokens(21_200))
    activity = Script(tokens(5, "turns_14"), tokens(6, "turns_14"))
    perf = make_perf(db, clock, {"context": context, "activity": activity})

    await run(perf, clock, "context", "activity")
    # A run of only the activity section leaves the context's comparison alone.
    await run(perf, clock, "activity")
    view = await run(perf, clock, "context")

    total = section(view, "context").metrics[0]
    assert (total.value, total.previous, total.text, total.previous_text) == (
        21_200,
        20_000,
        "21.2k",
        "20k",
    )
    assert total.change is not None
    assert (total.change.text, total.change.direction, total.change.tone) == (
        "▲ 1.2k",
        "up",
        "worse",
    )
    turns = section(view, "activity").metrics[0]
    assert (turns.value, turns.previous) == (6, 5)
    assert view.cards[0].id == "total"
    assert view.runs == 3


async def test_a_section_that_fails_keeps_its_error_and_the_run_goes_on(
    db: Database, clock: FakeClock
) -> None:
    perf = make_perf(
        db,
        clock,
        {"context": Script(RuntimeError("engine said: secret path")), "turns": Script(tokens(3))},
    )

    view = await run(perf, clock, "context", "turns")

    failed = section(view, "context")
    assert failed.error == "Could not measure it (RuntimeError)."
    assert failed.metrics == []
    assert section(view, "turns").metrics[0].value == 3
    assert view.last_run is not None
    assert view.running is None


async def test_an_error_after_a_good_run_shows_with_the_last_good_results(
    db: Database, clock: FakeClock
) -> None:
    perf = make_perf(db, clock, {"turns": Script(tokens(3), TimeoutError())})

    await run(perf, clock, "turns")
    view = await run(perf, clock, "turns")

    turns = section(view, "turns")
    assert turns.error == "Timed out."
    assert turns.metrics[0].value == 3


async def test_only_one_run_at_a_time(db: Database, clock: FakeClock) -> None:
    gate = asyncio.Event()

    async def slow() -> Collected:
        await gate.wait()
        return tokens(1)

    perf = make_perf(db, clock, {"turns": slow})
    started = await perf.start(["turns"])
    assert started.running is not None
    assert started.running.sections == ["turns"]

    with pytest.raises(ConflictError):
        await perf.start(["turns"])

    gate.set()
    await perf.settled()
    assert (await perf.view()).running is None
    await perf.start(["turns"])
    await perf.settled()


async def test_unknown_and_client_sections_cannot_be_run_by_the_daemon(
    db: Database, clock: FakeClock
) -> None:
    perf = make_perf(db, clock, {})

    for sections in (["nope"], ["mac"]):
        with pytest.raises(InvalidInputError):
            await perf.start(sections)


async def test_run_all_runs_every_daemon_section_in_page_order(
    db: Database, clock: FakeClock
) -> None:
    order: list[str] = []

    def recording(name: str) -> Callable[[], Awaitable[Collected]]:
        async def collect() -> Collected:
            order.append(name)
            return tokens(1)

        return collect

    perf = make_perf(db, clock, {name: recording(name) for name in ("gates", "context", "load")})

    view = await run(perf, clock)

    assert order == ["context", "load", "gates"]
    # Sections without a collector say so, and the Mac app's is not run.
    assert section(view, "turns").error == "Not measured on this daemon."
    assert section(view, "mac").error is None


async def test_a_restart_marks_the_run_in_progress_failed(db: Database, clock: FakeClock) -> None:
    store = PerfStore(db, clock)
    cut = await store.create(["turns"], BUILD, "Test Mac")
    perf = make_perf(db, clock, {"turns": Script(tokens(1))})

    await perf.started(ready_ms=850)

    assert await store.running() is None
    row = await db.fetch_one("SELECT state, error FROM perf_runs WHERE id = ?", (cut.id,))
    assert row is not None
    assert (row["state"], row["error"]) == ("failed", RESTARTED)
    start = await store.latest_start()
    assert start is not None
    assert start.ready_ms == 850
    # The failed run does not block the next.
    await perf.start(["turns"])
    await perf.settled()


async def test_clear_keeps_the_two_latest_runs_of_each_section(
    db: Database, clock: FakeClock
) -> None:
    context = Script(*(tokens(n) for n in (1, 2, 3)))
    turns = Script(*(tokens(n) for n in (10, 20, 30)))
    perf = make_perf(db, clock, {"context": context, "turns": turns})
    await run(perf, clock, "context", "turns")  # context 1, turns 10: no longer needed
    await run(perf, clock, "turns")  # turns 20
    await run(perf, clock, "context")  # context 2
    await run(perf, clock, "turns")  # turns 30
    await run(perf, clock, "context")  # context 3

    view = await perf.clear()

    assert view.runs == 4
    context_metric = section(view, "context").metrics[0]
    assert (context_metric.value, context_metric.previous) == (3, 2)
    turns_metric = section(view, "turns").metrics[0]
    assert (turns_metric.value, turns_metric.previous) == (30, 20)


async def test_clear_keeps_a_run_still_needed_by_another_section(
    db: Database, clock: FakeClock
) -> None:
    perf = make_perf(
        db, clock, {"context": Script(*(tokens(n) for n in (1, 2, 3))), "turns": Script(tokens(9))}
    )
    await run(perf, clock, "context", "turns")
    await run(perf, clock, "context")
    await run(perf, clock, "context")

    view = await perf.clear()

    assert view.runs == 3
    assert section(view, "turns").metrics[0].value == 9


async def test_what_changed_names_a_new_mcp_server_and_a_new_version(
    db: Database, clock: FakeClock
) -> None:
    before = tokens(20_000)
    before.facts = {"mcp_servers": ["github"], "skills": 10}
    after = tokens(25_000)
    after.facts = {"mcp_servers": ["github", "linear"], "skills": 10}
    small = Script(tokens(100, "turns_14"), tokens(400, "turns_14"))
    collectors: dict[str, Collector] = {"context": Script(before, after), "activity": small}
    await run(make_perf(db, clock, collectors), clock, "context", "activity")

    view = await run(
        make_perf(db, clock, collectors, Build("1.1.0", "def")), clock, "context", "activity"
    )

    # Activity moves neither better nor worse, so it is not listed.
    assert [(c.text, c.tone) for c in view.changes] == [
        (
            "Context cost, total +5k (Nest 1.0.0 to 1.1.0; new MCP server linear)",
            "worse",
        )
    ]


async def test_small_changes_are_not_listed(db: Database, clock: FakeClock) -> None:
    perf = make_perf(db, clock, {"context": Script(tokens(20_000), tokens(20_300))})
    await run(perf, clock, "context")

    view = await run(perf, clock, "context")

    assert view.changes == []


async def test_a_client_result_is_a_finished_run_of_its_section(
    db: Database, clock: FakeClock
) -> None:
    perf = make_perf(db, clock, {})

    await perf.record_client("mac", {"layout_ms": 800.0, "unknown": 1.0})
    view = await perf.record_client("mac", {"layout_ms": 600.0})

    mac = section(view, "mac")
    assert mac.runner == "mac"
    layout = next(m for m in mac.metrics if m.id == "layout_ms")
    assert (layout.value, layout.previous, layout.text) == (600, 800, "600 ms")
    assert layout.change is not None
    assert (layout.change.text, layout.change.tone) == ("▼ 25%", "better")
    assert [m.id for m in mac.metrics] == [
        "layout_ms",
        "memory_before",
        "memory_after",
    ]
    # The header's last run is the daemon's.
    assert view.last_run is None
    with pytest.raises(InvalidInputError):
        await perf.record_client("turns", {})
