"""Follows every session's transcript and publishes task and agent snapshots.

A tracker is built from the session's persisted events the first time it is needed (after
a restart too) without publishing, then catches up on new events, publishing what changed:
`session.tasks` when the task list changes, `session.agents` (agents and the background
summary) stored when an agent or background command starts or finishes and ephemeral for
activity.
"""

import asyncio

from pydantic import BaseModel, JsonValue

from harness.events import types
from harness.events.bus import EventBus
from harness.tracking.agents import Change
from harness.tracking.models import BackgroundSummary, TrackedAgent, TrackedTask
from harness.tracking.tracker import SessionTracker


class TrackingSnapshot(BaseModel):
    tasks: list[TrackedTask]
    agents: list[TrackedAgent]
    background: BackgroundSummary


class Tracking:
    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self._trackers: dict[str, SessionTracker] = {}
        # Serializes catching up, so no event is applied twice.
        self._lock = asyncio.Lock()

    async def sync(self, session_id: str) -> SessionTracker:
        async with self._lock:
            tracker = self._trackers.get(session_id)
            if tracker is None:
                tracker = self._trackers[session_id] = SessionTracker()
                for event in await self._bus.session_events(session_id):
                    tracker.apply(event)
                return tracker
            tasks_changed, change = False, Change.NONE
            for event in await self._bus.session_events(session_id, tracker.last_event_id):
                tasks, agents = tracker.apply(event)
                tasks_changed, change = tasks_changed or tasks, max(change, agents)
            await self._publish(session_id, tracker, tasks_changed, change)
            return tracker

    async def snapshot(self, session_id: str) -> TrackingSnapshot:
        tracker = await self.sync(session_id)
        return TrackingSnapshot(
            tasks=tracker.tasks.snapshot(),
            agents=tracker.agents.snapshot(),
            background=tracker.agents.background(),
        )

    async def summary(self, session_id: str) -> str | None:
        return (await self.sync(session_id)).summary

    async def _publish(
        self, session_id: str, tracker: SessionTracker, tasks_changed: bool, change: Change
    ) -> None:
        if tasks_changed:
            tasks: list[JsonValue] = [t.model_dump(mode="json") for t in tracker.tasks.snapshot()]
            await self._bus.publish(types.SESSION_TASKS, {"tasks": tasks}, session_id)
        if change is Change.NONE:
            return
        snapshot: list[JsonValue] = [a.model_dump(mode="json") for a in tracker.agents.snapshot()]
        agents: dict[str, JsonValue] = {
            "agents": snapshot,
            "background": tracker.agents.background().model_dump(mode="json"),
        }
        if change is Change.LIFECYCLE:
            await self._bus.publish(types.SESSION_AGENTS, agents, session_id)
        else:
            await self._bus.publish_ephemeral(types.SESSION_AGENTS, agents, session_id)
