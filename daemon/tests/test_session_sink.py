import asyncio
import logging
from contextlib import aclosing
from datetime import UTC, datetime, timedelta

import pytest

from nestd.config.models import PermissionMode
from nestd.events import types
from nestd.events.bus import EventBus
from nestd.providers.base import (
    AgentTask,
    CommandCatalog,
    EngineDetails,
    HookOutput,
    LimitHit,
    McpServer,
    ResultInfo,
    TextBlock,
    TokenUsage,
    ToolUseBlock,
    UsageInfo,
    UsageWindow,
)
from nestd.sessions.live import LiveSession
from nestd.sessions.models import Session
from nestd.sessions.sink import SessionSink, TurnEnd
from nestd.sessions.store import SessionStore
from nestd.storage.db import Database
from tests.fakes import FakeClock
from tests.recording_hooks import RecordingHooks
from tests.test_session_store import new_session


class RecordingTurns:
    def __init__(self, end: TurnEnd | None = None) -> None:
        self.calls: list[tuple[object, ...]] = []
        self.end: TurnEnd | None = end

    async def agent_active(self, live: LiveSession) -> None:
        self.calls.append(("active", live.session_id))

    async def how_ended(self, live: LiveSession, info: ResultInfo) -> TurnEnd | None:
        return self.end

    async def turn_finished(
        self, live: LiveSession, error: str | None, end: TurnEnd | None
    ) -> None:
        self.calls.append(("finished", live.session_id, error, end))

    async def run_stopped(self, live: LiveSession, error: str) -> None:
        self.calls.append(("stopped", error))

    async def background_tasks(self, live: LiveSession, running: int) -> None:
        self.calls.append(("background", running))

    async def permission_mode(self, live: LiveSession, mode: PermissionMode) -> None:
        self.calls.append(("mode", mode))

    async def checkpoint(self, live: LiveSession, checkpoint_id: str) -> None:
        self.calls.append(("checkpoint", checkpoint_id))

    async def message_taken(self, live: LiveSession, message_id: str, checkpoint_id: str) -> None:
        self.calls.append(("taken", message_id, checkpoint_id))


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
        errors=[],
        tokens=TokenUsage(input_tokens=3),
    )
    await sink.result(result)
    usage = UsageInfo(
        five_hour=UsageWindow(utilization=0.5, resets_at=datetime(2026, 1, 1, tzinfo=UTC)),
        seven_day=None,
    )
    await sink.usage(usage)
    # A background subagent can report after the turn ended: no new turn starts for it.
    await sink.subagent_usage("msg_1", TokenUsage(output_tokens=7))
    await sink.background_tasks(2)
    await sink.connectors([McpServer("claude.ai Gmail", "connected")])
    await sink.stopped("process ended")

    assert turns.calls == [
        ("active", session.id),
        ("active", session.id),
        ("finished", session.id, None, None),
        ("background", 2),
        ("stopped", "process ended"),
    ]
    assert hooks.messages == [session.id]
    assert hooks.results == [(session.id, result)]
    assert hooks.usages == [usage]
    assert hooks.subagent_usages == [(session.id, "msg_1", TokenUsage(output_tokens=7))]
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


async def test_thinking_and_subagent_text_stream_live_and_are_never_stored(
    db: Database, clock: FakeClock, bus: EventBus
) -> None:
    """B59: the finished blocks are stored as messages; their text streams before."""
    store = SessionStore(db, clock)
    session = await store.create(new_session())
    turns = RecordingTurns()
    sink = SessionSink(LiveSession(session.id), bus, store, turns, RecordingHooks(), None)

    async with aclosing(bus.subscribe()) as live:
        pending = asyncio.ensure_future(anext(live))
        await asyncio.sleep(0)
        await sink.thinking_delta("Let me", None)
        thought = await pending
        pending = asyncio.ensure_future(anext(live))
        await sink.subagent_delta("Found it", "toolu_1")
        written = await pending

    assert turns.calls == [("active", session.id), ("active", session.id)]
    assert [(e.type, e.id, e.session_id, e.payload) for e in (thought, written)] == [
        (
            types.SESSION_THINKING_DELTA,
            None,
            session.id,
            {"text": "Let me", "parent_tool_use_id": None},
        ),
        (
            types.SESSION_SUBAGENT_DELTA,
            None,
            session.id,
            {"text": "Found it", "parent_tool_use_id": "toolu_1"},
        ),
    ]
    assert await bus.session_events(session.id) == []


HOOK = HookOutput(
    hook_id="h1",
    hook_name="PostToolUse:Edit",
    hook_event="PostToolUse",
    outcome="success",
    system_message="Formatted 2 files",
)


async def test_hook_messages_are_stored_without_starting_a_turn(
    db: Database, clock: FakeClock, bus: EventBus
) -> None:
    """B59: a SessionStart or Stop hook speaks outside any turn."""
    store = SessionStore(db, clock)
    session = await store.create(new_session())
    turns = RecordingTurns()
    sink = SessionSink(LiveSession(session.id), bus, store, turns, RecordingHooks(), None)

    await sink.hook(HOOK)

    assert turns.calls == []
    events = await bus.session_events(session.id)
    assert [(e.type, e.payload) for e in events] == [
        (
            types.SESSION_HOOK,
            {
                "hook_id": "h1",
                "hook_name": "PostToolUse:Edit",
                "hook_event": "PostToolUse",
                "outcome": "success",
                "exit_code": None,
                "system_message": "Formatted 2 files",
                "output": None,
            },
        )
    ]


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
    # The conversation before a /clear stays this session's (BUG-41).
    assert await store.provider_session_ids() == {"old", "new"}
    assert await store.find_by_provider_session("old") == stored


async def test_a_cut_conversation_is_done_once_the_run_reports_its_new_session(
    db: Database, clock: FakeClock, bus: EventBus
) -> None:
    """B59: the run resumed `old` cut; its own id clears the pending cut."""
    store = SessionStore(db, clock)
    session = await store.create(new_session())
    await store.update(session.id, provider_session_id="old", fork_from="old", fork_at="a-1")
    turns = RecordingTurns()
    sink = SessionSink(
        LiveSession(session.id), bus, store, turns, RecordingHooks(), "old", forking="old"
    )

    await sink.provider_session_id("old")
    pending = await store.get(session.id)
    await sink.provider_session_id("forked")
    await sink.message_taken("m1", "cp-1")
    done = await store.get(session.id)

    assert (pending.fork_from, pending.fork_at) == ("old", "a-1")
    assert (done.provider_session_id, done.fork_from, done.fork_at) == ("forked", None, None)
    assert await store.find_by_provider_session("old") == done
    assert turns.calls == [("taken", "m1", "cp-1")]


@pytest.mark.parametrize("end", ["handoff", "stopped", "limit"])
async def test_a_result_that_is_no_failure_is_marked(
    db: Database, clock: FakeClock, bus: EventBus, end: TurnEnd
) -> None:
    """B59: an error result that only makes way for the next message, or of a turn the
    user stopped, is no failure; nor is one the usage limit cut off (B78).
    """
    store = SessionStore(db, clock)
    session = await store.create(new_session())
    turns = RecordingTurns(end)
    sink = SessionSink(LiveSession(session.id), bus, store, turns, RecordingHooks(), None)
    result = ResultInfo(
        is_error=True, subtype="error_during_execution", duration_ms=5, num_turns=1, errors=["x"]
    )

    await sink.result(result)

    (event,) = [e for e in await bus.session_events(session.id) if e.type == "session.result"]
    assert event.payload[end] is True
    assert event.payload["errors"] == ["x"]
    assert turns.calls == [("finished", session.id, "x", end)]


async def test_limit_reports_of_a_turn_are_kept_together_for_its_end(
    db: Database, clock: FakeClock, bus: EventBus
) -> None:
    """B78: the event naming the window and the cut-off message can come in either order."""
    store = SessionStore(db, clock)
    session = await store.create(new_session())
    live = LiveSession(session.id)
    sink = SessionSink(live, bus, store, RecordingTurns(), RecordingHooks(), None)
    resets = datetime(2026, 10, 17, 15, tzinfo=UTC)

    await sink.limit_hit(LimitHit(cut_off=True))
    await sink.limit_hit(LimitHit(window="five_hour", resets_at=resets))
    await sink.limit_hit(LimitHit())

    assert live.limit_hit == LimitHit(window="five_hour", resets_at=resets, cut_off=True)


async def notices(bus: EventBus, session_id: str) -> list[object]:
    return [e.payload for e in await bus.session_events(session_id) if e.type == "session.notice"]


async def test_notices_are_stored_and_a_retry_only_once_a_turn(
    db: Database, clock: FakeClock, bus: EventBus
) -> None:
    """BUG-41, BUG-44: transcript notes; a turn may retry many times, one note says so."""
    store = SessionStore(db, clock)
    session = await store.create(new_session())
    turns = RecordingTurns()
    sink = SessionSink(LiveSession(session.id), bus, store, turns, RecordingHooks(), None)
    result = ResultInfo(is_error=False, subtype="success", duration_ms=5, num_turns=1, errors=[])

    await sink.notice("api_retry", "API error, retrying")
    await sink.notice("api_retry", "API error (overloaded), retrying")
    await sink.notice("model_fallback", "Switched to claude-sonnet-5")
    await sink.result(result)
    await sink.notice("api_retry", "API error, retrying")
    await sink.notice("compacted", "Conversation compacted")
    await sink.permission_mode("plan")
    await sink.checkpoint("msg-1")

    assert await notices(bus, session.id) == [
        {"kind": "api_retry", "text": "API error, retrying"},
        {"kind": "model_fallback", "text": "Switched to claude-sonnet-5"},
        {"kind": "api_retry", "text": "API error, retrying"},
        {"kind": "compacted", "text": "Conversation compacted"},
    ]
    assert turns.calls[-2:] == [("mode", "plan"), ("checkpoint", "msg-1")]


class BrokenTurns:
    async def agent_active(self, live: LiveSession) -> None:
        raise RuntimeError("active")

    async def how_ended(self, live: LiveSession, info: ResultInfo) -> TurnEnd | None:
        raise RuntimeError("how")

    async def turn_finished(
        self, live: LiveSession, error: str | None, end: TurnEnd | None
    ) -> None:
        raise RuntimeError("finished")

    async def permission_mode(self, live: LiveSession, mode: PermissionMode) -> None:
        raise RuntimeError("mode")

    async def run_stopped(self, live: LiveSession, error: str) -> None:
        raise RuntimeError("stopped")

    async def background_tasks(self, live: LiveSession, running: int) -> None:
        raise RuntimeError("background")

    async def checkpoint(self, live: LiveSession, checkpoint_id: str) -> None:
        raise RuntimeError("checkpoint")

    async def message_taken(self, live: LiveSession, message_id: str, checkpoint_id: str) -> None:
        raise RuntimeError("taken")


class BrokenHooks:
    async def state_changed(self, session: Session) -> None:
        raise LookupError("state")

    async def turn_starting(self, session: Session) -> None:
        raise LookupError("start")

    async def message(self, session_id: str) -> None:
        raise LookupError("message")

    async def turn_result(self, session_id: str, info: ResultInfo) -> None:
        raise LookupError("result")

    async def usage(self, info: UsageInfo, account_id: str | None) -> None:
        raise LookupError("usage")

    async def subagent_usage(self, session_id: str, message_id: str, tokens: TokenUsage) -> None:
        raise LookupError("subagent usage")

    async def connectors_reported(self, session_id: str, servers: list[McpServer]) -> None:
        raise LookupError("connectors")

    async def commands_reported(self, session_id: str, catalog: CommandCatalog) -> None:
        raise LookupError("commands")

    async def engine_reported(self, details: EngineDetails) -> None:
        raise LookupError("engine")

    async def purged(self, session_id: str) -> None:
        raise LookupError("purged")

    async def rewound(self, session: Session, *, conversation: bool, files: bool) -> None:
        raise LookupError("rewound")


async def test_no_error_reaches_the_agent_run(
    db: Database, clock: FakeClock, bus: EventBus, caplog: pytest.LogCaptureFixture
) -> None:
    """The run treats an error from the sink as the agent crashing; bookkeeping must not."""
    store = SessionStore(db, clock)
    session = await store.create(new_session())
    sink = SessionSink(LiveSession(session.id), bus, store, BrokenTurns(), BrokenHooks(), None)
    await db.close()  # every event and store write fails from here on
    result = ResultInfo(is_error=False, subtype="success", duration_ms=5, num_turns=1, errors=[])

    with caplog.at_level(logging.WARNING):
        await sink.message([TextBlock(text="Hello")], None)
        await sink.text_delta("Hel")
        await sink.thinking(True)
        await sink.thinking_delta("Hmm", None)
        await sink.subagent_delta("Hi", "toolu_1")
        await sink.hook(HOOK)
        await sink.result(result)
        await sink.usage(UsageInfo(five_hour=None, seven_day=None))
        await sink.subagent_usage("msg_1", TokenUsage())
        await sink.connectors([])
        await sink.commands(CommandCatalog())
        await sink.engine_details(EngineDetails())
        await sink.provider_session_id("sdk-1")
        await sink.background_tasks(1)
        await sink.task(AgentTask(task_id="t1", phase="started"))
        await sink.notice("compacted", "Conversation compacted")
        await sink.permission_mode("plan")
        await sink.checkpoint("msg-1")
        await sink.message_taken("m1", "cp-1")
        await sink.stopped("process ended")

    kinds = [record.getMessage().split(" of session ")[0] for record in caplog.records]
    assert kinds == [
        "starting a turn",
        "the message event",
        "the message hooks",
        "starting a turn",
        "starting a turn",
        "starting a turn",
        "starting a turn",
        "the hook event",
        "how the turn ended",
        "the result event",
        "the turn result hooks",
        "ending the turn",
        "the usage event",
        "the usage hooks",
        "the subagent usage hooks",
        "the connector report",
        "the command report",
        "the engine report",
        "storing the agent's session id",
        "the background task count",
        "the task event",
        "the message hooks",
        "the notice event",
        "the mode change",
        "the message checkpoint",
        "the message read in the turn",
        "the run's end",
    ]
