"""A turn can end while helpers it started go on in the background (B133). The chat's work
is not ready then, so its review and its "finished" notice wait for them.

When the last helper ends, the chat's agent usually takes a turn to read the result, and
that turn's end settles the chat as any turn's does. When no such turn starts, as after the
user stopped the helper, the chat is settled here a moment later. Held chats are kept in
memory only: on start, chats whose helpers a previous process left running are settled too.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)

# Long enough for the turn after a helper's end to start.
SETTLE_SECONDS = 15.0


class ReviewHold:
    def __init__(self, settle: Callable[[str, bool], Awaitable[None]]) -> None:
        """`settle` gets the chat and whether the user still has to hear its turn ended."""
        self._settle = settle
        # Held chats, to whether the user still has to hear.
        self._held: dict[str, bool] = {}
        self._timers: dict[str, asyncio.Task[None]] = {}

    def holds(self, session_id: str) -> bool:
        return session_id in self._held

    def hold(self, session_id: str, *, notify: bool) -> None:
        self._stop_timer(session_id)
        self._held[session_id] = self._held.get(session_id, False) or notify

    def helpers_ended(self, session_id: str) -> None:
        if session_id in self._held and session_id not in self._timers:
            self._timers[session_id] = asyncio.create_task(self._settle_later(session_id))

    def release(self, session_id: str) -> None:
        self._stop_timer(session_id)
        self._held.pop(session_id, None)

    def shutdown(self) -> None:
        for timer in self._timers.values():
            timer.cancel()
        self._timers.clear()

    def _stop_timer(self, session_id: str) -> None:
        timer = self._timers.pop(session_id, None)
        if timer is not None:
            timer.cancel()

    async def _settle_later(self, session_id: str) -> None:
        await asyncio.sleep(SETTLE_SECONDS)
        self._timers.pop(session_id, None)
        notify = self._held.pop(session_id, False)
        try:
            await self._settle(session_id, notify)
        except Exception:
            logger.exception("could not settle session %s after its helpers", session_id)
