"""Bookkeeping around an agent's work (hooks, audits, reports) can fail without ending it."""

import logging
from collections.abc import Awaitable

logger = logging.getLogger(__name__)


async def isolated(kind: str, session_id: str, work: Awaitable[object]) -> None:
    """Await `work`; an error is logged by kind and swallowed, so the agent's run and the
    session's turn carry on (D048).
    """
    await isolated_or(kind, session_id, work, None)


async def isolated_or[T](kind: str, session_id: str, work: Awaitable[T], fallback: T) -> T:
    """`isolated` for work with an answer: `fallback` when it fails."""
    try:
        return await work
    except Exception as error:
        logger.warning(
            "%s of session %s failed (%s: %s)", kind, session_id, type(error).__name__, error
        )
        return fallback
