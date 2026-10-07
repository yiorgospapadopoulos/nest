"""Session state changes: stored, announced as an event, then passed to the hooks."""

from collections.abc import Mapping

from pydantic import JsonValue

from harness.events import types
from harness.events.bus import EventBus
from harness.sessions.hooks import SessionHooks
from harness.sessions.models import Session, SessionState
from harness.sessions.store import SessionStore


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
    ) -> Session:
        """`turn` adds the turn boundary the change marks: `turn_start` or `duration_ms` (D045)."""
        session = await self._store.update(session_id, state=state, last_error=error)
        await self._bus.publish(
            types.SESSION_STATE, {"state": state, "error": error, **(turn or {})}, session_id
        )
        await self._hooks.state_changed(session)
        return session
