"""Starts habits on events in any project (B42, D109): a chat looks stuck, failed, is
ready for review, or its pull request's checks failed. These are the `notify` events of
those kinds. Pixie chats, habit runs and chats the habit's own pixie started never start
its habits; the last keeps a pixie's runs from starting each other.
"""

import asyncio
import logging
from contextlib import aclosing, suppress

from pydantic import JsonValue

from nestd.events import types
from nestd.events.bus import EventBus, SubscriptionOverflowError
from nestd.events.models import Event
from nestd.pixies.habit_models import TRIGGERS
from nestd.pixies.habit_store import HabitStore
from nestd.pixies.scheduler import HabitScheduler
from nestd.sessions.errors import SessionNotFoundError
from nestd.sessions.models import PIXIE_REPO_PREFIX
from nestd.sessions.store import SessionStore
from nestd.tracking.steps import one_line

logger = logging.getLogger(__name__)

# Characters of an event's text a run's prompt quotes.
TEXT_CHARS = 200


class HabitTriggers:
    def __init__(
        self,
        *,
        bus: EventBus,
        sessions: SessionStore,
        habits: HabitStore,
        scheduler: HabitScheduler,
    ) -> None:
        self._bus = bus
        self._sessions = sessions
        self._habits = habits
        self._scheduler = scheduler
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        after = await self._bus.last_id()
        self._task = asyncio.create_task(self._listen(after))

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    async def observe(self, event: Event) -> None:
        """Queue the event for every enabled habit it triggers."""
        payload = event.payload
        kind = payload.get("kind")
        session_id = payload.get("session_id")
        repo = payload.get("repo")
        if (
            event.type != types.NOTIFY
            or kind not in TRIGGERS
            or not isinstance(session_id, str)
            or not isinstance(repo, str)
            or repo.startswith(PIXIE_REPO_PREFIX)
        ):
            return
        try:
            session = await self._sessions.get(session_id)
        except SessionNotFoundError:
            return
        entry: dict[str, JsonValue] = {
            "kind": kind,
            "session_id": session.id,
            "title": session.title,
            "project": session.repo,
            "text": one_line(str(payload.get("text", "")), TEXT_CHARS),
            "at": event.ts.isoformat(),
        }
        for habit in await self._habits.enabled():
            if kind not in habit.triggers:
                continue
            if session.started_by_pixie == habit.pixie_id:
                continue
            await self._scheduler.queue_trigger(habit, entry)

    async def _listen(self, after: int) -> None:
        """Follow events stored after `after`; after falling behind, from the last seen."""
        while True:
            try:
                async with aclosing(self._bus.subscribe(after)) as events:
                    async for event in events:
                        after = event.id or after
                        try:
                            await self.observe(event)
                        except Exception as error:
                            logger.warning("habit trigger failed (%s)", type(error).__name__)
            except SubscriptionOverflowError:
                logger.warning("habit triggers fell behind the events; following again")
