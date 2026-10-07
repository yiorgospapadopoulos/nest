import asyncio

from pydantic import JsonValue

from harness.events import types
from harness.events.bus import EventBus
from harness.events.models import Event
from harness.storage.db import Database
from harness.tracking.service import Tracking
from tests.async_support import until
from tests.fakes import FakeClock
from tests.tracking_fixture import create_task, message, start_agent_message, text, tool_use


async def publish_all(bus: EventBus, events: list[tuple[str, dict[str, JsonValue]]]) -> None:
    for event_type, payload in events:
        await bus.publish(event_type, payload, "s1")


class Collector:
    """Everything published on the bus, up to a marker event."""

    def __init__(self, bus: EventBus) -> None:
        self.bus = bus
        self.seen: list[Event] = []
        self.task = asyncio.create_task(self._collect())

    async def _collect(self) -> None:
        async for event in self.bus.subscribe():
            self.seen.append(event)

    async def until_marker(self) -> list[Event]:
        await self.bus.publish_ephemeral("marker", {})
        await until(lambda: bool(self.seen) and self.seen[-1].type == "marker")
        seen, self.seen = self.seen[:-1], []
        return seen


async def test_sync_loads_history_quietly_then_publishes_changes(
    db: Database, clock: FakeClock
) -> None:
    bus = EventBus(db, clock)
    tracking = Tracking(bus)
    use, result = create_task(1, "One", "Doing one")
    await publish_all(
        bus,
        [
            (types.SESSION_CREATED, {"session": {"cwd": None}}),
            (types.SESSION_STATE, {"state": "running", "error": None}),
            (types.SESSION_MESSAGE, use),
        ],
    )

    collector = Collector(bus)
    await until(lambda: bus.subscriber_count == 1)
    await tracking.sync("s1")
    quiet = await collector.until_marker()
    await publish_all(bus, [(types.SESSION_MESSAGE, result)])
    await tracking.sync("s1")
    await publish_all(bus, [(types.SESSION_MESSAGE, message(tool_use("b", "Bash", {})))])
    await tracking.sync("s1")
    await publish_all(bus, [(types.SESSION_MESSAGE, start_agent_message("a1"))])
    await tracking.sync("s1")
    await publish_all(bus, [(types.SESSION_MESSAGE, message(text("All done.")))])
    await tracking.sync("s1")
    published = [e for e in await collector.until_marker() if e.type != types.SESSION_MESSAGE]
    collector.task.cancel()

    assert quiet == []
    assert [(e.type, e.id is not None) for e in published] == [
        (types.SESSION_TASKS, True),
        (types.SESSION_AGENTS, False),  # the task's result: activity only
        (types.SESSION_AGENTS, False),
        (types.SESSION_AGENTS, True),  # a subagent started
    ]
    tasks = published[0].payload["tasks"]
    assert isinstance(tasks, list)
    assert [t["subject"] for t in tasks] == ["One"]  # pyright: ignore[reportIndexIssue, reportArgumentType, reportCallIssue, reportOptionalSubscript]
    agents = published[-1].payload["agents"]
    assert isinstance(agents, list)
    assert [a["id"] for a in agents] == ["main", "a1"]  # pyright: ignore[reportIndexIssue, reportArgumentType, reportCallIssue, reportOptionalSubscript]
    summary = published[-1].payload["background"]
    assert isinstance(summary, dict)
    assert (summary["running"], summary["completed"]) == (1, 0)
    snapshot = await tracking.snapshot("s1")
    assert [item.id for item in snapshot.background.items] == ["a1"]
    assert [t.id for t in snapshot.tasks] == ["1"]
    assert [a.id for a in snapshot.agents] == ["main", "a1"]
    assert await tracking.summary("s1") == "All done."


async def test_an_unknown_session_has_only_the_main_agent(db: Database, clock: FakeClock) -> None:
    snapshot = await Tracking(EventBus(db, clock)).snapshot("nobody")

    assert snapshot.tasks == []
    assert [a.id for a in snapshot.agents] == ["main"]
    assert snapshot.background.model_dump() == {"running": 0, "completed": 0, "items": []}
