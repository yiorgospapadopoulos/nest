"""Saving a session's fields and announcing them as `session.updated`, which clients
apply to the session they hold.
"""

from nestd.events import types
from nestd.events.bus import EventBus
from nestd.sessions.models import Session
from nestd.sessions.store import SessionStore


async def save_changes(
    store: SessionStore, bus: EventBus, session_id: str, changes: dict[str, object]
) -> Session:
    session = await store.update(session_id, **changes)
    await announce_changes(bus, session, set(changes))
    return session


async def announce_changes(bus: EventBus, session: Session, names: set[str]) -> None:
    """Fields of `session` that were saved: clients take the session as it is now."""
    await bus.publish(
        types.SESSION_UPDATED,
        {
            "changes": session.model_dump(mode="json", include=names),
            "session": session.model_dump(mode="json"),
        },
        session.id,
    )
