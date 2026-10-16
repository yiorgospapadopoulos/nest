"""Chats paused at the subscription's usage limit (B78).

A turn the usage limit cut off ends without failing and pauses its chat: the pause is
stored on the session (it survives a restart) and announced. While a chat is paused,
messages sent to it wait in its queue and nothing starts on its own. The daemon goes on at
the pause's `resume_at`: a margin after the reset the engine named, or a fixed delay when
it named none. Which chats are paused, and when they go on, is also kept here in memory,
so the turn runner can check it without waiting.
"""

from datetime import datetime, timedelta
from typing import Literal

from nestd.clock import Clock
from nestd.events import types
from nestd.events.bus import EventBus
from nestd.providers.base import LimitHit
from nestd.sessions.models import LimitPause
from nestd.sessions.store import SessionStore
from nestd.sessions.updates import save_changes

# The daemon goes on this long after the reset the engine named, so the limit has surely
# lifted by then.
RESUME_MARGIN = timedelta(seconds=30)
# When the engine named no reset, the daemon tries again after this long; a limit that
# still holds pauses the chat again.
UNKNOWN_RESET_DELAY = timedelta(minutes=30)

# Why a pause ended.
type ClearReason = Literal["reset", "resumed", "stopped", "archived", "closed"]


class LimitPauses:
    def __init__(self, store: SessionStore, bus: EventBus, clock: Clock) -> None:
        self._store = store
        self._bus = bus
        self._clock = clock
        # Paused chats by session id, to when they go on.
        self._due: dict[str, datetime] = {}

    def paused(self, session_id: str) -> bool:
        return session_id in self._due

    def take_due(self, now: datetime) -> list[str]:
        """The paused chats whose time to go on has come, the earliest first; their pauses
        end here, so nothing else ends them too. The caller announces each (`cleared`).
        """
        due = sorted((at, sid) for sid, at in self._due.items() if at <= now)
        for _, session_id in due:
            del self._due[session_id]
        return [session_id for _, session_id in due]

    async def load(self) -> None:
        """After a restart: the pauses the previous process stored."""
        for session_id, pause in await self._store.limit_pauses():
            self._due[session_id] = pause.resume_at

    async def pause(self, session_id: str, hit: LimitHit) -> LimitPause:
        """Pause the chat until the limit resets; a chat paused already gets the new time."""
        now = self._clock.now()
        resume_at = (
            now + UNKNOWN_RESET_DELAY
            if hit.resets_at is None
            else max(hit.resets_at, now) + RESUME_MARGIN
        )
        pause = LimitPause(
            window=hit.window, resets_at=hit.resets_at, resume_at=resume_at, since=now
        )
        # Noted first, so a Stop meanwhile finds the pause to clear.
        self._due[session_id] = resume_at
        await save_changes(self._store, self._bus, session_id, {"limit_pause": pause})
        await self._bus.publish(
            types.SESSION_LIMIT_PAUSED, {"limit_pause": pause.model_dump(mode="json")}, session_id
        )
        return pause

    async def clear(self, session_id: str, reason: ClearReason) -> bool:
        """End the chat's pause; False when it is not paused (or another call ended it)."""
        if self._due.pop(session_id, None) is None:
            return False
        await self.cleared(session_id, reason)
        return True

    async def cleared(self, session_id: str, reason: ClearReason) -> None:
        """Store and announce that the chat's pause ended."""
        await save_changes(self._store, self._bus, session_id, {"limit_pause": None})
        await self._bus.publish(types.SESSION_LIMIT_CLEARED, {"reason": reason}, session_id)

    def forget(self, session_id: str) -> None:
        """The chat is being deleted, with its pause."""
        self._due.pop(session_id, None)
