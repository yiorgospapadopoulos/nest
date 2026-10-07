import asyncio
import logging
from contextlib import aclosing
from datetime import UTC, datetime, timedelta

import pytest

from harness.events import types
from harness.events.bus import EventBus
from harness.providers.base import (
    AgentTask,
    CommandCatalog,
    EngineDetails,
    McpServer,
    ResultInfo,
    TextBlock,
    TokenUsage,
    ToolUseBlock,
    UsageInfo,
    UsageWindow,
)
from harness.sessions.live import LiveSession
from harness.sessions.models import Session
from harness.sessions.sink import SessionSink
from harness.sessions.store import SessionStore
from harness.storage.db import Database
from tests.fakes import FakeClock
from tests.recording_hooks import RecordingHooks
from tests.test_session_store import new_session


class RecordingTurns:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    async def agent_active(self, live: LiveSession) -> None:
        self.calls.append(("active", live.session_id))

    async def turn_finished(self, live: LiveSession) -> None:
        self.calls.append(("finished", live.session_id))

    async def run_stopped(self, live: LiveSession, error: str) -> None:
        self.calls.append(("stopped", error))

    async def background_tasks(self, live: LiveSession, running: int) -> None:
        self.calls.append(("background", running))


@pytest.fixture
def bus(db: Database, clock: FakeClock) -> EventBus:
    return EventBus(db, clock)


async def test_sink_turns_provider_reports_into_events_and_turn_boundaries(
    db: Database, clock: FakeClock, bus: EventBus
) -> None:
    store = SessionStore(db, clock)
    session = await store.create(new_session())
    turns = RecordingTurns()
    hooks = RecordingHooks()
    sink = SessionSink(LiveSession(session.id), bus, store, turns, hooks, None)

    async with aclosing(bus.subscribe()) as live:
        pending = asyncio.ensure_future(anext(live))
        await asyncio.sleep(0)
        await sink.text_delta("Hel")
        delta = await pending
    await sink.message([TextBlock(text="Hello"), ToolUseBlock(id="t", name="Bash", input={})], "p")
    result = ResultInfo(
        is_error=False,
        subtype="success",
        duration_ms=5,
        num_turns=1,
        cost_usd=0.1,
        errors=[],
        tokens=TokenUsage(input_tokens=3),
    )
    await sink.result(result)
    usage = UsageInfo(
        five_hour=UsageWindow(utilization=0.5, resets_at=datetime(2026, 1, 1, tzinfo=UTC)),
        seven_day=None,
    )
    await sink.usage(usage)
    await sink.background_tasks(2)
    await sink.connectors([McpServer("claude.ai Gmail", "connected")])
    await sink.stopped("process ended")

    assert turns.calls == [
        ("active", session.id),
        ("active", session.id),
        ("finished", session.id),
        ("background", 2),
        ("stopped", "process ended"),
    ]
    assert hooks.messages == [session.id]
    assert hooks.results == [(session.id, result)]
    assert hooks.usages == [usage]
    assert hooks.connectors == [(session.id, [McpServer("claude.ai Gmail", "connected")])]
    assert delta.type == types.SESSION_DELTA
    assert delta.id is None
    assert delta.session_id == session.id
    assert delta.payload == {"text": "Hel"}
    events = await bus.session_events(session.id)
    assert [(e.type, e.payload) for e in events] == [
        (
            types.SESSION_MESSAGE,
            {
                "blocks": [
                    {"type": "text", "text": "Hello"},
                    {"type": "tool_use", "id": "t", "name": "Bash", "input": {}},
                ],
                "parent_tool_use_id": "p",
            },
        ),
        (
            types.SESSION_RESULT,
            {
                "is_error": False,
                "subtype": "success",
                "duration_ms": 5,
                "num_turns": 1,
                "cost_usd": 0.1,
                "errors": [],
                "tokens": {
                    "input_tokens": 3,
                    "output_tokens": 0,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 0,
                },
            },
        ),
    ]
    rows = await db.fetch_all(
        "SELECT session_id, payload FROM events WHERE type = ?", (types.USAGE_UPDATED,)
    )
    assert [(r["session_id"], r["payload"]) for r in rows] == [
        (
            None,
            '{"five_hour": {"utilization": 0.5, "resets_at": "2026-01-01T00:00:00Z"},'
            ' "seven_day": null}',
        )
    ]


async def test_task_updates_are_stored_without_starting_a_turn(
    db: Database, clock: FakeClock, bus: EventBus
) -> None:
    store = SessionStore(db, clock)
    session = await store.create(new_session())
    turns = RecordingTurns()
    hooks = RecordingHooks()
    sink = SessionSink(LiveSession(session.id), bus, store, turns, hooks, None)

    await sink.task(AgentTask(task_id="t1", phase="finished", tool_use_id="a1", status="failed"))

    assert turns.calls == []
    assert hooks.messages == [session.id]
    events = await bus.session_events(session.id)
    assert [(e.type, e.payload) for e in events] == [
        (
            types.SESSION_AGENT_TASK,
            {
                "task_id": "t1",
                "phase": "finished",
                "tool_use_id": "a1",
                "task_type": None,
                "description": None,
                "background": False,
                "status": "failed",
            },
        )
    ]


async def test_thinking_is_announced_live_and_never_stored(
    db: Database, clock: FakeClock, bus: EventBus
) -> None:
    store = SessionStore(db, clock)
    session = await store.create(new_session())
    turns = RecordingTurns()
    sink = SessionSink(LiveSession(session.id), bus, store, turns, RecordingHooks(), None)

    async with aclosing(bus.subscribe()) as live:
        pending = asyncio.ensure_future(anext(live))
        await asyncio.sleep(0)
        await sink.thinking(True)
        started = await pending
        pending = asyncio.ensure_future(anext(live))
        await sink.thinking(False)
        ended = await pending

    assert turns.calls == [("active", session.id), ("active", session.id)]
    assert [(e.type, e.id, e.session_id, e.payload) for e in (started, ended)] == [
        (types.SESSION_THINKING, None, session.id, {"active": True}),
        (types.SESSION_THINKING, None, session.id, {"active": False}),
    ]
    assert await bus.session_events(session.id) == []


async def test_provider_session_id_is_stored_once_per_change(
    db: Database, clock: FakeClock, bus: EventBus
) -> None:
    store = SessionStore(db, clock)
    session = await store.create(new_session())
    sink = SessionSink(
        LiveSession(session.id), bus, store, RecordingTurns(), RecordingHooks(), "old"
    )

    clock.advance(timedelta(seconds=1))
    await sink.provider_session_id("old")
    unchanged = await store.get(session.id)
    clock.advance(timedelta(seconds=1))
    await sink.provider_session_id("new")
    written_at = clock.current
    clock.advance(timedelta(seconds=1))
    await sink.provider_session_id("new")
    stored = await store.get(session.id)

    assert unchanged.updated_at == session.created_at
    assert unchanged.provider_session_id is None
    assert stored.provider_session_id == "new"
    assert stored.updated_at == written_at


class BrokenTurns:
    async def agent_active(self, live: LiveSession) -> None:
        raise RuntimeError("active")

    async def turn_finished(self, live: LiveSession) -> None:
        raise RuntimeError("finished")

    async def run_stopped(self, live: LiveSession, error: str) -> None:
        raise RuntimeError("stopped")

    async def background_tasks(self, live: LiveSession, running: int) -> None:
        raise RuntimeError("background")


class BrokenHooks:
    async def state_changed(self, session: Session) -> None:
        raise LookupError("state")

    async def message(self, session_id: str) -> None:
        raise LookupError("message")

    async def turn_result(self, session_id: str, info: ResultInfo) -> None:
        raise LookupError("result")

    async def usage(self, info: UsageInfo) -> None:
        raise LookupError("usage")

    async def connectors_reported(self, session_id: str, servers: list[McpServer]) -> None:
        raise LookupError("connectors")

    async def commands_reported(self, session_id: str, catalog: CommandCatalog) -> None:
        raise LookupError("commands")

    async def engine_reported(self, details: EngineDetails) -> None:
        raise LookupError("engine")


async def test_no_error_reaches_the_agent_run(
    db: Database, clock: FakeClock, bus: EventBus, caplog: pytest.LogCaptureFixture
) -> None:
    """The run treats an error from the sink as the agent crashing; bookkeeping must not."""
    store = SessionStore(db, clock)
    session = await store.create(new_session())
    sink = SessionSink(LiveSession(session.id), bus, store, BrokenTurns(), BrokenHooks(), None)
    await db.close()  # every event and store write fails from here on
    result = ResultInfo(
        is_error=False, subtype="success", duration_ms=5, num_turns=1, cost_usd=0.1, errors=[]
    )

    with caplog.at_level(logging.WARNING):
        await sink.message([TextBlock(text="Hello")], None)
        await sink.text_delta("Hel")
        await sink.thinking(True)
        await sink.result(result)
        await sink.usage(UsageInfo(five_hour=None, seven_day=None))
        await sink.connectors([])
        await sink.commands(CommandCatalog())
        await sink.engine_details(EngineDetails())
        await sink.provider_session_id("sdk-1")
        await sink.background_tasks(1)
        await sink.task(AgentTask(task_id="t1", phase="started"))
        await sink.stopped("process ended")

    kinds = [record.getMessage().split(" of session ")[0] for record in caplog.records]
    assert kinds == [
        "starting a turn",
        "the message event",
        "the message hooks",
        "starting a turn",
        "starting a turn",
        "the result event",
        "the turn result hooks",
        "ending the turn",
        "the usage event",
        "the usage hooks",
        "the connector report",
        "the command report",
        "the engine report",
        "storing the agent's session id",
        "the background task count",
        "the task event",
        "the message hooks",
        "the run's end",
    ]
