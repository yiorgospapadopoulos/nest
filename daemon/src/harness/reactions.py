"""What follows a session's progress: task and agent tracking, reviews, notifications,
token usage and connector status.
"""

from harness.connectors.registry import ConnectorRegistry
from harness.notifications.notifier import Notifier, NotifyKind
from harness.providers.base import McpServer, ResultInfo, UsageInfo
from harness.review.watch import ReviewWatcher
from harness.sessions.models import Session, SessionState
from harness.tracking.service import Tracking
from harness.tracking.steps import one_line
from harness.usage.store import UsageStore

MAX_NOTICE_LENGTH = 200


class SessionReactions:
    """The session hooks of the running daemon."""

    def __init__(
        self,
        tracking: Tracking,
        reviews: ReviewWatcher,
        notifier: Notifier,
        usage: UsageStore,
        connectors: ConnectorRegistry,
    ) -> None:
        self._tracking = tracking
        self._reviews = reviews
        self._notifier = notifier
        self._usage = usage
        self._connectors = connectors

    async def state_changed(self, session: Session) -> None:
        tracker = await self._tracking.sync(session.id)
        if session.state is SessionState.IDLE:
            # A review announces itself; otherwise the user hears the turn finished.
            if await self._reviews.turn_ended(session) is None:
                await self._notify(session, "finished", tracker.summary or "The turn finished.")
        elif session.state is SessionState.FAILED:
            await self._notify(session, "failed", session.last_error or "The session failed.")

    async def message(self, session_id: str) -> None:
        await self._tracking.sync(session_id)

    async def turn_result(self, session_id: str, info: ResultInfo) -> None:
        await self._usage.record_turn(session_id, info.tokens)

    async def usage(self, info: UsageInfo) -> None:
        await self._usage.update_limits(info)

    async def connectors_reported(self, session_id: str, servers: list[McpServer]) -> None:
        await self._connectors.report(session_id, servers)

    async def _notify(self, session: Session, kind: NotifyKind, text: str) -> None:
        await self._notifier.notify(
            kind, session.id, session.repo, session.title, one_line(text, MAX_NOTICE_LENGTH)
        )
