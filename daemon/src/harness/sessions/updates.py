"""Saving a session's fields and announcing them as `session.updated`, which clients
apply to the session they hold.
"""

from harness.events import types
from harness.events.bus import EventBus
from harness.sessions.models import Session
from harness.sessions.store import SessionStore


async def save_changes(
    store: SessionStore, bus: EventBus, session_id: str, changes: dict[str, object]
) -> Session:
    session = await store.update(session_id, **changes)
    await bus.publish(
        types.SESSION_UPDATED,
        {
            "changes": session.model_dump(mode="json", include=set(changes)),
            "session": session.model_dump(mode="json"),
        },
        session_id,
    )
    return session


async def set_git_violation(
    store: SessionStore, bus: EventBus, session_id: str, flagged: bool
) -> Session:
    """Set or clear the flag that holds publishing until the user acknowledges what the
    agent did with git (D013 layer 4); announced only when it changes (BUG-50).
    """
    session = await store.get(session_id)
    if session.git_violation == flagged:
        return session
    return await save_changes(store, bus, session_id, {"git_violation": flagged})
