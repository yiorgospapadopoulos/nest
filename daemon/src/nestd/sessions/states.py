"""Session state changes: stored, announced as an event, then passed to the hooks.

A failing hook is only logged: the change itself has happened (D048).
"""

from collections.abc import Mapping

from pydantic import JsonValue

from nestd.events import types
from nestd.events.bus import EventBus
from nestd.sessions.bookkeeping import isolated
from nestd.sessions.hooks import SessionHooks
from nestd.sessions.models import Session, SessionState
from nestd.sessions.store import SessionStore


class StateWriter:
    def __init__(self, store: SessionStore, bus: EventBus, hooks: SessionHooks) -> None:
        self._store = store
        self._bus = bus
        self._hooks = hooks

    async def set(
        self,
        session_id: str,
        state: SessionState,
        error: str | None = None,
        turn: Mapping[str, JsonValue] | None = None,
        details: Mapping[str, JsonValue] | None = None,
    ) -> Session:
        """`turn` adds the turn boundary the change marks: `turn_start` or `duration_ms`
        (D045); `details` what clients show with the error, such as a local model's server
        that went away (B106).
        """
        session = await self._store.update(session_id, state=state, last_error=error)
        await self._bus.publish(
            types.SESSION_STATE,
            {"state": state, "error": error, **(turn or {}), **(details or {})},
            session_id,
        )
        await isolated("the state hooks", session_id, self._hooks.state_changed(session))
        return session
